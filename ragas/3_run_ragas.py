from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
RAGAS_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import (
    BASE_MODEL_BF16,
    LLM_MAX_TOKENS,
    LLM_REASONING_EFFORT,
    LLM_TEMPERATURE,
    VLLM_API_URL,
    M_ADAPTER_NAME,
)

RAGAS_JUDGE = "o" # o | m
DEFAULT_DATASET_PATH = RAGAS_DIR / "ragas_test_outputs.json"
RESULTS_DIR = RAGAS_DIR / "results"
JUDGE_MODEL_NAME = M_ADAPTER_NAME if RAGAS_JUDGE == "m" else BASE_MODEL_BF16
RECALL_METRIC_NAME = "non_llm_context_recall"
FFN_METRIC_NAME = "faithfulness"
INTENT_ORDER = ["risk", "law", "design", "general"]
REPORT_HEADER_MIN_WIDTH = 79

CONFIG = {
    "recall_pass_threshold": 0.7,
    "faithfulness_pass_threshold": 1.1,
}

MODE_METRICS = {
    "recall": [RECALL_METRIC_NAME],
    "ffn": [FFN_METRIC_NAME],
    "all": [RECALL_METRIC_NAME, FFN_METRIC_NAME],
}


def _get(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _contexts_to_text_list(contexts: list | None) -> list[str]:
    """list[str] 또는 list[dict] context를 text 리스트로 정규화."""
    if not contexts:
        return []
    out = []
    for item in contexts:
        if isinstance(item, dict):
            out.append(str(item.get("text", "")))
        else:
            out.append(str(item))
    return out


_INTENT_NOT_PROVIDED = object()


def _parse_intent_limit(value: str) -> int | None:
    value = str(value).strip().lower()
    if value == "all":
        return None
    try:
        limit = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError("값은 양의 정수 또는 'all'이어야 합니다.") from e
    if limit <= 0:
        raise argparse.ArgumentTypeError("값은 1 이상의 정수 또는 'all'이어야 합니다.")
    return limit


def _collect_intent_limits(args) -> dict[str, int | None]:
    intent_limits = {}
    for intent in INTENT_ORDER:
        value = getattr(args, intent, _INTENT_NOT_PROVIDED)
        if value is not _INTENT_NOT_PROVIDED:
            intent_limits[intent] = value
    return intent_limits


def _single_intent_for_filename(intent_limits: dict[str, int | None]) -> str | None:
    """파일명에 쓸 intent 하나만 지정된 경우 그 intent 이름 반환, 아니면 None."""
    if len(intent_limits) != 1:
        return None
    return next(iter(intent_limits))


def _should_include_intent(
    intent: str,
    intent_limits: dict[str, int | None],
    selected_counts: dict[str, int],
) -> bool:
    if not intent_limits:
        return True
    if intent not in intent_limits:
        return False
    limit = intent_limits[intent]
    if limit is None:
        return True
    return selected_counts.get(intent, 0) < limit


def load_ragas_dataset(
    json_path: Path,
    mode: str,
    intent_limits: dict[str, int | None] | None = None,
):
    """RAGAS EvaluationDataset 형식으로 로드하고 mode별 필수 필드를 검증한다."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        from ragas import EvaluationDataset
        from ragas.dataset_schema import SingleTurnSample
    except ImportError:
        try:
            from ragas.evaluation import EvaluationDataset
            from ragas.dataset_schema import SingleTurnSample
        except ImportError as e:
            print("Error: ragas 패키지 필요. pip install ragas")
            raise SystemExit(1) from e

    samples = []
    sample_rows = []
    skipped = 0
    intent_limits = intent_limits or {}
    selected_counts = {intent: 0 for intent in intent_limits}
    needs_reference_contexts = mode in ("recall", "all")
    needs_retrieved_contexts = mode in ("recall", "ffn", "all")
    needs_response = mode in ("ffn", "all")
    missing_retrieved = []
    missing_reference_contexts = []
    missing_response = []
    for raw_idx, s in enumerate(data.get("samples", []), start=1):
        sample_id = str(s.get("id") or f"sample-{raw_idx}")
        intent = s.get("intent") or (sample_id.split("-", 1)[0] if "-" in sample_id else "unknown")
        if not _should_include_intent(intent, intent_limits, selected_counts):
            continue
        response = s.get("response")
        response_text = str(response).strip() if response is not None else ""

        if needs_response and not response_text:
            missing_response.append(sample_id)
            skipped += 1
            continue

        user_input = _get(s, "user_input", "question") or ""
        raw_reference_contexts = s.get("reference_contexts")
        if needs_reference_contexts and raw_reference_contexts is None:
            missing_reference_contexts.append(sample_id)
        ref_texts = _contexts_to_text_list(raw_reference_contexts)

        retrieved = s.get("retrieved_contexts")
        if needs_retrieved_contexts and retrieved is None:
            missing_retrieved.append(sample_id)
            retrieved_texts = []
        else:
            retrieved_texts = _contexts_to_text_list(retrieved)
        reference = s.get("reference")
        reference_text = str(reference).strip() if reference is not None else ""
        sample_no = raw_idx

        samples.append(
            SingleTurnSample(
                user_input=user_input,
                response=response_text or None,
                retrieved_contexts=retrieved_texts,
                reference_contexts=ref_texts,
                reference=reference_text or None,
            )
        )
        sample_rows.append(
            {
                "no": sample_no,
                "id": sample_id,
                "intent": intent,
                "ref_ctx": len(ref_texts),
                "ret_ctx": len(retrieved_texts),
                "user_input": user_input,
                "facility_info": s.get("facility_info") or {},
                "full_response": s.get("full_response") or "",
            }
        )
        if intent in selected_counts:
            selected_counts[intent] += 1

    if missing_retrieved:
        preview = ", ".join(missing_retrieved[:5])
        print(
            f"Error: {mode} 모드에는 retrieved_contexts가 필요합니다. "
            f"누락 {len(missing_retrieved)}건. 예: {preview}"
        )
        raise SystemExit(1)
    if missing_reference_contexts:
        preview = ", ".join(missing_reference_contexts[:5])
        print(
            f"Error: {mode} 모드에는 reference_contexts가 필요합니다. "
            f"누락 {len(missing_reference_contexts)}건. 예: {preview}"
        )
        raise SystemExit(1)
    if missing_response and needs_response:
        print(f"  (response 비어 있어 제외: {skipped}건)")
    if not samples:
        if intent_limits:
            selected_desc = ", ".join(
                f"{intent}={'all' if limit is None else limit}"
                for intent, limit in intent_limits.items()
            )
            print(f"Error: 선택한 의도 조건에 맞는 샘플이 없습니다. ({selected_desc})")
        else:
            print("Error: 평가할 샘플이 없습니다. JSON에서 response를 채운 뒤 다시 실행하세요.")
        raise SystemExit(1)

    return EvaluationDataset(samples=samples), len(samples), skipped, sample_rows


def _extract_json_from_text(text: str) -> str:
    """모델 출력에서 JSON 블록 또는 첫 번째 {...} 를 추출."""
    import re
    text = (text or "").strip()
    # ```json ... ``` 또는 ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    # 첫 번째 { 부터 마지막 } 까지 (중첩 괄호 고려)
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text


def _repair_json_string(text: str) -> str:
    """닫는 괄호/중괄호가 일부 누락된 JSON 문자열을 가볍게 복구한다."""
    text = (text or "").strip()
    if not text:
        return text

    result = []
    stack = []
    in_string = False
    escape = False
    closer = {"{": "}", "[": "]"}
    opener = {"}": "{", "]": "["}

    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == "\\":
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            result.append(ch)
            in_string = not in_string
            continue
        if in_string:
            result.append(ch)
            continue
        if ch in "{[":
            stack.append(ch)
            result.append(ch)
            continue
        if ch in "}]":
            expected_open = opener[ch]
            while stack and stack[-1] != expected_open:
                result.append(closer[stack.pop()])
            if stack and stack[-1] == expected_open:
                stack.pop()
            result.append(ch)
            continue
        result.append(ch)

    repaired = "".join(result).rstrip()
    if in_string:
        repaired += '"'
    while repaired.endswith(","):
        repaired = repaired[:-1].rstrip()
    repaired += "".join(closer[ch] for ch in reversed(stack))
    return repaired


class VLLMInstructorLLM:
    """vLLM OpenAI 호환 엔드포인트를 RAGAS judge용 래퍼로 감싼다. 응답 텍스트에서 JSON을 추출해 Pydantic response_model로 파싱한다."""

    def __init__(
        self,
        client,
        model_name: str,
        max_new_tokens: int = 1024,
        temperature: float = 0.0,
        reasoning_effort: str = "low",
    ):
        self._client = client
        self._model_name = model_name
        self._max_new_tokens = max_new_tokens
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort

    def generate(self, prompt: str, response_model):
        """동기: vLLM judge 생성 후 response_model로 파싱."""
        import json

        from pydantic import BaseModel

        if not isinstance(response_model, type):
            response_model = type(response_model)

        text = str(prompt)
        # 구조화 출력 요청 추가 (모델이 JSON을 더 잘 따르도록)
        base_instruction = (
            "\n\nRespond with a single JSON object only, no other text. "
            "Keys must match the required schema exactly."
        )
        retry_instruction = (
            "\nReturn strictly valid JSON. Do not omit closing brackets or braces. "
            "If a field is a list, always return a JSON array for it."
        )

        last_error = None
        last_raw = ""
        for attempt in range(3):
            prompt_text = text + base_instruction
            if attempt > 0:
                prompt_text += retry_instruction

            kwargs = {
                "model": self._model_name,
                "messages": [{"role": "user", "content": prompt_text}],
                "temperature": self._temperature,
                "max_tokens": self._max_new_tokens,
            }
            if self._reasoning_effort:
                kwargs["reasoning_effort"] = self._reasoning_effort
            response = self._client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content if response.choices else ""
            if isinstance(raw, list):
                parts = []
                for item in raw:
                    if isinstance(item, dict):
                        parts.append(str(item.get("text", "")))
                    else:
                        parts.append(str(getattr(item, "text", item)))
                raw = "".join(parts)

            last_raw = str(raw or "")
            json_str = _extract_json_from_text(last_raw)
            repaired_json_str = _repair_json_string(json_str)

            try:
                try:
                    obj = json.loads(json_str)
                except json.JSONDecodeError:
                    obj = json.loads(repaired_json_str)

                if issubclass(response_model, BaseModel):
                    return response_model.model_validate(obj)
                return obj
            except Exception as e:
                last_error = e

        raw_preview = last_raw[:800].replace("\n", "\\n")
        raise RuntimeError(
            f"judge structured output parse failed after 3 attempts: {last_error}; "
            f"raw={raw_preview}"
        )

    async def agenerate(self, prompt: str, response_model):
        """비동기: 이벤트 루프에서 동기 generate를 스레드로 실행."""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.generate(prompt, response_model)
        )


def _make_vllm_judge_llm():
    """vLLM 서버에 올라온 BF16 base model을 Judge LLM으로 사용."""
    from openai import OpenAI
    from ragas.llms.base import InstructorBaseRagasLLM

    client = OpenAI(base_url=VLLM_API_URL, api_key="EMPTY")

    class _VLLMJudgeLLM(VLLMInstructorLLM, InstructorBaseRagasLLM):
        """vLLM judge wrapper."""
        pass

    return _VLLMJudgeLLM(
        client=client,
        model_name=JUDGE_MODEL_NAME,
        max_new_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        reasoning_effort=LLM_REASONING_EFFORT,
    )


class _CollectionsEvalResult:
    """collections 메트릭 수동 실행 결과. to_pandas() 및 score 속성으로 기대 인터페이스 제공."""

    def __init__(self, scores, dataset):
        self.scores = scores
        self.dataset = dataset
        keys = list(scores[0].keys()) if scores and scores[0] else []
        self._scores_dict = {k: [d.get(k, float("nan")) for d in scores] for k in keys}
        import numpy as np

        with np.errstate(invalid="ignore"):
            self.score = (
                {k: float(np.nanmean(v)) for k, v in self._scores_dict.items()}
                if self._scores_dict else None
            )

    def to_pandas(self, batch_size=None, batched=False):
        import pandas as pd

        if not self.scores:
            return pd.DataFrame()
        return pd.DataFrame(self.scores)


def _has_retrieved_contexts(sample) -> bool:
    ctx = getattr(sample, "retrieved_contexts", None)
    return bool(ctx)


def _metric_kwargs(metric_name: str, sample) -> dict:
    if metric_name == FFN_METRIC_NAME:
        return {
            "user_input": getattr(sample, "user_input", "") or "",
            "response": getattr(sample, "response", "") or "",
            "retrieved_contexts": getattr(sample, "retrieved_contexts", []) or [],
        }
    return {}


def _unwrap_metric_result(metric_result):
    return metric_result.value if hasattr(metric_result, "value") else metric_result


async def _score_non_llm_context_recall(metric, sample):
    reference_contexts = getattr(sample, "reference_contexts", None)
    retrieved_contexts = getattr(sample, "retrieved_contexts", None)

    if not reference_contexts:
        return 1.0 if not retrieved_contexts else 0.0
    if not retrieved_contexts:
        return 0.0
    return _unwrap_metric_result(await metric.single_turn_ascore(sample))


async def _run_collections_evaluation(dataset, metrics, *, output_path=None, sample_rows=None, mode=None):
    """샘플별로 필요한 kwargs만 넘겨 collections/legacy 메트릭을 실행한다."""
    samples = getattr(dataset, "samples", None) or list(dataset)
    scores = []
    total = len(samples)
    for idx, sample in enumerate(samples, start=1):
        row = {}
        has_contexts = _has_retrieved_contexts(sample)
        for metric in metrics:
            name = getattr(metric, "name", metric.__class__.__name__)
            try:
                if name == RECALL_METRIC_NAME and hasattr(metric, "single_turn_ascore"):
                    row[name] = await _score_non_llm_context_recall(metric, sample)
                elif name == FFN_METRIC_NAME and not has_contexts:
                    row[name] = 1.0
                elif hasattr(metric, "ascore"):
                    kwargs = _metric_kwargs(name, sample)
                    mr = await metric.ascore(**kwargs)
                    row[name] = _unwrap_metric_result(mr)
                elif hasattr(metric, "single_turn_ascore"):
                    row[name] = _unwrap_metric_result(await metric.single_turn_ascore(sample))
                else:
                    row[name] = float("nan")
            except Exception as e:
                raise RuntimeError(f"{name} 평가 실패 (sample #{idx}): {e}") from e
        score_str = " | ".join(f"{k}={v:.4f}" for k, v in row.items() if isinstance(v, float))
        print(f"  [{idx}/{total}] {score_str}")
        scores.append(row)

        if output_path and sample_rows and mode:
            _save_partial_report(scores, dataset, sample_rows, mode, output_path)

    return _CollectionsEvalResult(scores=scores, dataset=dataset)


def _save_partial_report(scores, dataset, sample_rows, mode, output_path):
    import pandas as pd
    partial_result = _CollectionsEvalResult(scores=scores, dataset=dataset)
    df = partial_result.to_pandas()
    df = _attach_sample_metadata(df, sample_rows[:len(scores)])
    summary_lines, df = _build_summary_lines(df, mode)
    sample_score_table = _build_sample_score_table(df, mode)
    report_text = _build_text_report(
        summary_lines=summary_lines,
        sample_score_table=sample_score_table,
        df=df,
        sample_rows=sample_rows,
        mode=mode,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)


def _build_metrics(judge_llm, metric_names):
    metrics = []
    for name in metric_names:
        if name == FFN_METRIC_NAME:
            try:
                from ragas.metrics.collections import Faithfulness
            except ImportError:
                from ragas.metrics import Faithfulness

            metrics.append(Faithfulness(llm=judge_llm))
        elif name == RECALL_METRIC_NAME:
            # ragas 0.4.3에서는 collections re-export가 없어 내부 모듈에서 직접 가져온다.
            from ragas.metrics._context_recall import NonLLMContextRecall

            metrics.append(NonLLMContextRecall())
    return metrics


def run_evaluation(dataset, judge_llm, metric_names=None, *, output_path=None, sample_rows=None, mode=None):
    """RAGAS 평가 실행. 선택한 메트릭만 수동 루프로 평가한다."""
    import asyncio

    if metric_names is None:
        metric_names = MODE_METRICS["all"]

    metrics = _build_metrics(judge_llm, metric_names)
    if not metrics:
        raise RuntimeError("실행할 메트릭이 없습니다.")
    return asyncio.run(_run_collections_evaluation(
        dataset, metrics,
        output_path=output_path, sample_rows=sample_rows, mode=mode,
    ))


def _resolve_mode(args) -> str:
    if getattr(args, "recall", False):
        return "recall"
    if getattr(args, "ffn", False):
        return "ffn"
    return "all"


def _default_output_path(mode: str, intent_limits: dict[str, int | None] | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    intent = _single_intent_for_filename(intent_limits or {}) if intent_limits else None
    if intent:
        return RESULTS_DIR / f"result_{mode}_{intent}_{stamp}.txt"
    return RESULTS_DIR / f"result_{mode}_{stamp}.txt"


def _format_metric_value(value) -> str:
    import math

    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "-"
    return f"{number:.4f}"


def _attach_sample_metadata(df, sample_rows):
    if len(df) != len(sample_rows):
        return df
    df = df.copy()
    df.insert(0, "no", [row["no"] for row in sample_rows])
    df.insert(1, "id", [row["id"] for row in sample_rows])
    df.insert(2, "intent", [row["intent"] for row in sample_rows])
    df["ref_ctx"] = [row["ref_ctx"] for row in sample_rows]
    df["ret_ctx"] = [row["ret_ctx"] for row in sample_rows]
    return df


def _build_summary_title(mode: str) -> str:
    recall_col = RECALL_METRIC_NAME
    ffn_col = FFN_METRIC_NAME
    r_th = CONFIG["recall_pass_threshold"]
    f_th = CONFIG["faithfulness_pass_threshold"]
    if mode == "recall":
        return f"Summary [{recall_col}(>={r_th})  accuracy]"
    if mode == "ffn":
        return f"Summary [{ffn_col}(>={f_th})  accuracy]"
    return (
        f"Summary [{recall_col}(>={r_th})  {ffn_col}(>={f_th})  accuracy]"
    )


OVERALL_ACCURACY_SUFFIX_WIDTH = 20


def _append_overall_accuracy(summary_lines, overall_correct, df):
    """Overall Accuracy 한 줄을 고정폭 우측 정렬로 summary_lines에 추가."""
    suffix = f"{overall_correct * 100:.2f}% ({int(df['correct'].sum())}/{len(df)})"
    summary_lines.append(
        "Overall Accuracy : " + f"{suffix:>{OVERALL_ACCURACY_SUFFIX_WIDTH}}"
    )


def _build_summary_lines(df, mode):
    recall_col = RECALL_METRIC_NAME
    ffn_col = FFN_METRIC_NAME
    recall_mean_col = f"{recall_col}_mean"
    ffn_mean_col = f"{ffn_col}_mean"
    title = _build_summary_title(mode)
    divider = "=" * max(REPORT_HEADER_MIN_WIDTH, len(title))
    summary_lines = [divider, title, divider]

    if len(df) == 0:
        summary_lines.append("No evaluation results.")
    elif "intent" not in df.columns:
        summary_lines.append(df.to_string(index=False))
    elif mode == "all" and recall_col in df.columns and ffn_col in df.columns:
        r_ok = CONFIG["recall_pass_threshold"]
        f_ok = CONFIG["faithfulness_pass_threshold"]
        df = df.copy()
        df["correct"] = (df[recall_col] >= r_ok) & (df[ffn_col] >= f_ok)
        by_intent = df.groupby("intent", sort=False).agg(
            **{
                recall_mean_col: (recall_col, "mean"),
                ffn_mean_col: (ffn_col, "mean"),
                "correct_count": ("correct", "sum"),
                "count": ("correct", "count"),
            }
        )
        by_intent["correct_rate"] = (
            by_intent["correct_count"] / by_intent["count"]
        ).round(4)
        by_intent = by_intent.drop(columns=["correct_count", "count"]).round(4)
        intent_order = [x for x in INTENT_ORDER if x in by_intent.index]
        by_intent = by_intent.reindex(intent_order)
        display_intent = by_intent[[recall_mean_col, ffn_mean_col]].rename(
            columns={recall_mean_col: "recall_mean", ffn_mean_col: "faithfulness_mean"}
        )
        overall_correct = df["correct"].sum() / len(df)
        summary_lines.append("[By Intent Mean] ")
        summary_lines.append(display_intent.to_string())
        _append_overall_accuracy(summary_lines, overall_correct, df)
    elif mode == "recall" and recall_col in df.columns:
        r_ok = CONFIG["recall_pass_threshold"]
        df = df.copy()
        df["correct"] = df[recall_col] >= r_ok
        by_intent = df.groupby("intent", sort=False).agg(
            **{
                recall_mean_col: (recall_col, "mean"),
                "correct_rate": ("correct", "mean"),
            }
        ).round(4)
        intent_order = [x for x in INTENT_ORDER if x in by_intent.index]
        by_intent = by_intent.reindex(intent_order)
        display_intent = by_intent[[recall_mean_col]].rename(
            columns={recall_mean_col: "recall_mean"}
        )
        overall_correct = df["correct"].sum() / len(df)
        summary_lines.append("[By Intent Mean] ")
        summary_lines.append(display_intent.to_string())
        _append_overall_accuracy(summary_lines, overall_correct, df)
    elif mode == "ffn" and ffn_col in df.columns:
        f_ok = CONFIG["faithfulness_pass_threshold"]
        df = df.copy()
        df["correct"] = df[ffn_col] >= f_ok
        by_intent = df.groupby("intent", sort=False).agg(
            **{
                ffn_mean_col: (ffn_col, "mean"),
                "correct_rate": ("correct", "mean"),
            }
        ).round(4)
        intent_order = [x for x in INTENT_ORDER if x in by_intent.index]
        by_intent = by_intent.reindex(intent_order)
        display_intent = by_intent[[ffn_mean_col]].rename(
            columns={ffn_mean_col: "faithfulness_mean"}
        )
        overall_correct = df["correct"].sum() / len(df)
        summary_lines.append("[By Intent Mean] ")
        summary_lines.append(display_intent.to_string())
        _append_overall_accuracy(summary_lines, overall_correct, df)
    else:
        summary_lines.append(df.to_string(index=False))

    return summary_lines, df


def _sample_score_header_line(columns, col_widths):
    """Sample Scores / Failed Samples 공통 헤더 한 줄. 컬럼별 고정폭 오른쪽 정렬, 컬럼 간 공백 1칸."""
    header_parts = [
        f"{str(c):>{col_widths.get(c, 10)}}" for c in columns
    ]
    return " ".join(header_parts)


def _build_sample_score_table(df, mode):
    if len(df) == 0:
        return "No sample scores."

    columns = ["no", "id", "intent"]
    rename_map = {
        "no": "no",
        "id": "id",
        "intent": "intent",
        "correct": "result",
        "ref_ctx": "ref_ctx",
        "ret_ctx": "ret_ctx",
    }

    if mode in ("recall", "all") and RECALL_METRIC_NAME in df.columns:
        columns.append(RECALL_METRIC_NAME)
        rename_map[RECALL_METRIC_NAME] = "recall"
    if mode in ("ffn", "all") and FFN_METRIC_NAME in df.columns:
        columns.append(FFN_METRIC_NAME)
        rename_map[FFN_METRIC_NAME] = "ffn"
    if "correct" in df.columns:
        columns.append("correct")
    if mode in ("recall", "all"):
        columns.extend(["ref_ctx", "ret_ctx"])
    elif mode == "ffn":
        columns.append("ret_ctx")

    display_df = df[columns].copy().rename(columns=rename_map)
    for metric_col in ("recall", "ffn"):
        if metric_col in display_df.columns:
            display_df[metric_col] = display_df[metric_col].map(_format_metric_value)
    if "result" in display_df.columns:
        display_df["result"] = display_df["result"].apply(lambda x: "PASS" if x else "-")
    col_widths = {"no": 5, "id": 12, "intent": 8, "recall": 10, "ffn": 10, "result": 8, "ref_ctx": 9, "ret_ctx": 9}
    formatters = {
        col: (lambda w: lambda x: f"{str(x):>{w}}")(col_widths.get(col, 10))
        for col in display_df.columns
    }
    table_str = display_df.to_string(index=False, formatters=formatters)
    header_line = _sample_score_header_line(display_df.columns, col_widths)
    lines = table_str.split("\n")
    lines[0] = header_line
    return "\n".join(lines)


FAILED_SECTION_DIVIDER_WIDTH = 79


def _sample_score_columns_for_mode(mode):
    """mode에 따른 Sample Scores 컬럼 순서(display 이름). _build_sample_score_table과 동일."""
    cols = ["no", "id", "intent"]
    if mode in ("recall", "all"):
        cols.append("recall")
    if mode in ("ffn", "all"):
        cols.append("ffn")
    cols.append("result")
    if mode in ("recall", "all"):
        cols.extend(["ref_ctx", "ret_ctx"])
    elif mode == "ffn":
        cols.append("ret_ctx")
    return cols


def _build_failed_samples_section(df, sample_rows, mode):
    """PASS하지 못한 샘플만 모아 포맷된 블록(질문·full_response·CLI)으로 반환. 샘플 간 줄바꿈 5회."""
    if "correct" not in df.columns or len(sample_rows) < len(df):
        return []
    failed_mask = df["correct"] == False
    if not failed_mask.any():
        return []
    failed_df = df.loc[failed_mask].copy()
    failed_table_str = _build_sample_score_table(failed_df, mode)
    lines_stripped = failed_table_str.rstrip("\n").split("\n")
    if len(lines_stripped) <= 1:
        return []
    col_widths = {"no": 5, "id": 12, "intent": 8, "recall": 10, "ffn": 10, "result": 8, "ref_ctx": 9, "ret_ctx": 9}
    header_line = _sample_score_header_line(
        _sample_score_columns_for_mode(mode), col_widths
    )
    data_lines = lines_stripped[1:]
    sep_eq = "=" * FAILED_SECTION_DIVIDER_WIDTH
    sep_dash = "-" * FAILED_SECTION_DIVIDER_WIDTH
    out = [">>> Failed Samples:"]
    for i, idx in enumerate(failed_df.index):
        if i >= len(data_lines):
            break
        if i > 0:
            out.extend(["", "", "", "", ""])
        row = sample_rows[idx]
        user_input_raw = row.get("user_input") or ""
        facility_info = row.get("facility_info") or {}
        facility_json = json.dumps(facility_info, ensure_ascii=False, indent=2)
        facility_shell = facility_json.replace("'", "'\\''")
        user_input_escaped = user_input_raw.replace("\\", "\\\\").replace('"', '\\"')
        cli_block = (
            f'python -m src.services.chat_service \\\n'
            f'  --question "{user_input_escaped}" \\\n'
            f"  --facility-json '{facility_shell}'"
        )
        full_response = row.get("full_response") or ""
        if "## 근거 문서 점수" in full_response:
            classification_marker = "[ 분류 코드:"
            if classification_marker in full_response:
                full_response = full_response.replace(
                    classification_marker,
                    "\n" + sep_dash + "\n" + classification_marker,
                    1,
                )
            else:
                full_response = full_response.replace(
                    "## 근거 문서 점수",
                    "\n" + sep_dash + "\n## 근거 문서 점수",
                    1,
                )
        out.append(sep_eq)
        out.append(header_line)
        out.append(data_lines[i])
        out.append(sep_eq)
        out.append("## 사용자 질문")
        out.append("")
        out.append(user_input_raw)
        out.append("")
        out.append("")
        out.append(sep_dash)
        out.append(full_response)
        out.append("")
        out.append("")
        out.append(sep_dash)
        out.append(cli_block)
    return out


def _build_text_report(
    summary_lines,
    sample_score_table,
    df=None,
    sample_rows=None,
    mode=None,
):
    report_lines = list(summary_lines)
    report_lines.extend(
        [
            "",
            "",
            "[Sample Scores]",
            sample_score_table,
            "",
            "=" * FAILED_SECTION_DIVIDER_WIDTH,
        ]
    )
    if df is not None and sample_rows is not None and mode is not None:
        report_lines.extend([""] * 10)
        report_lines.extend(_build_failed_samples_section(df, sample_rows, mode))
    return "\n".join(report_lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="RAGAS 평가",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="평가할 샘플 JSON 경로. 미지정 시 intent별 ragas_test_<intent>_outputs.json 또는 ragas_test_outputs.json 사용.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="평가 결과 TXT 경로. 미지정 시 ragas/results/result_<mode>_년월일_시분초.txt 로 저장.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--recall",
        action="store_true",
        help="reference_contexts vs retrieved_contexts 기반 recall만 평가",
    )
    mode_group.add_argument(
        "--ffn",
        action="store_true",
        help="response vs retrieved_contexts 기반 faithfulness만 평가",
    )
    mode_group.add_argument(
        "--all",
        action="store_true",
        help="non_llm_context_recall + faithfulness 모두 평가",
    )
    parser.add_argument(
        "--risk",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="risk 의도 샘플만 평가. 예: --risk 10, --risk all",
    )
    parser.add_argument(
        "--law",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="law 의도 샘플만 평가. 예: --law 10, --law all",
    )
    parser.add_argument(
        "--design",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="design 의도 샘플만 평가. 예: --design 10, --design all",
    )
    parser.add_argument(
        "--general",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="general 의도 샘플만 평가. 예: --general 10, --general all",
    )
    args = parser.parse_args()
    mode = _resolve_mode(args)
    metric_names = MODE_METRICS[mode]
    intent_limits = _collect_intent_limits(args)
    if args.data is None:
        intent = _single_intent_for_filename(intent_limits)
        args.data = RAGAS_DIR / f"ragas_test_{intent}_outputs.json" if intent else DEFAULT_DATASET_PATH
    if args.out is None:
        args.out = _default_output_path(mode, intent_limits)

    print("1. 데이터셋 로드...")
    dataset, n_samples, skipped, sample_rows = load_ragas_dataset(
        args.data,
        mode,
        intent_limits=intent_limits,
    )
    print(f"   샘플 수: {n_samples}")

    print("2. vLLM 심판관 LLM 연결 (GPT-OSS-20B BF16 base)...")
    try:
        judge_llm = _make_vllm_judge_llm()
    except Exception as e:
        print(f"Error (vLLM judge 초기화): {e}")
        sys.exit(1)

    print("3. RAGAS 평가 실행...")
    print(f"   결과 실시간 저장: {args.out}")
    try:
        result = run_evaluation(
            dataset, judge_llm, metric_names,
            output_path=args.out, sample_rows=sample_rows, mode=mode,
        )
    except Exception as e:
        print(f"Error (evaluate): {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    summary_lines = []
    sample_score_table = "No sample scores."
    df = None
    if hasattr(result, "to_pandas"):
        df = result.to_pandas()
        df = _attach_sample_metadata(df, sample_rows)
        summary_lines, df = _build_summary_lines(df, mode)
        sample_score_table = _build_sample_score_table(df, mode)
    else:
        summary_lines.append(str(result))

    print()
    print("\n".join(summary_lines))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report_text = _build_text_report(
        summary_lines=summary_lines,
        sample_score_table=sample_score_table,
        df=df,
        sample_rows=sample_rows,
        mode=mode,
    )
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()
