from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
RAGAS_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

INTENT_ORDER = ["risk", "law", "design", "general"]

from src.core.graph import app_graph
from src.services.json_parser import facility_json_to_text


def _build_initial_state(question: str, facility_info: Dict[str, Any]) -> Dict[str, Any]:
    facility_text = facility_json_to_text(facility_info).strip() if facility_info else ""
    return {
        "question": question,
        "facility_info": facility_text,
        "search_query": "",
        "target_intents": [],
        "target_material": None,
        "target_equipment": None,
        "accident_docs": [],
        "chemical_docs": [],
        "law_docs": [],
        "design_docs": [],
        "search_metadata": {},
        "partial_answers": [],
        "node_outputs": {},
        "final_answer": "",
    }


def _preview_text(raw_text: str, limit: int = 20) -> str:
    text = " ".join((raw_text or "").strip().split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _score_or_zero(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def _doc_to_metadata(category: str, doc: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    source = doc.get("source") or doc.get("title") or ""
    primary_score = doc.get("primary_score")
    if primary_score is None:
        primary_score = doc.get("match_score")
    if primary_score is None:
        primary_score = doc.get("score")

    rerank_score = doc.get("rerank_score")
    if rerank_score is None:
        rerank_score = doc.get("score")

    return {
        "category": category,
        "source": str(source),
        "preview": _preview_text(raw_text),
        "primary_score": _score_or_zero(primary_score),
        "rerank_score": _score_or_zero(rerank_score),
    }


def _collect_retrieved_contexts(final_state: Dict[str, Any]) -> tuple[List[str], List[Dict[str, Any]]]:
    texts: List[str] = []
    metadata: List[Dict[str, Any]] = []

    for key, category in [
        ("accident_docs", "accidents"),
        ("chemical_docs", "chemicals"),
        ("law_docs", "laws"),
        ("design_docs", "designs"),
    ]:
        docs = final_state.get(key) or []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            raw_text = str(doc.get("text") or doc.get("chunk_text") or "").strip()
            if not raw_text:
                continue
            texts.append(raw_text)
            metadata.append(_doc_to_metadata(category=category, doc=doc, raw_text=raw_text))

    return texts, metadata


async def _run_sample(sample: Dict[str, Any], thread_id: str) -> Dict[str, Any]:
    question = str(sample.get("user_input") or "").strip()
    facility_info = sample.get("facility_info") or {}
    initial_state = _build_initial_state(question=question, facility_info=facility_info)
    config = {"configurable": {"thread_id": thread_id}}

    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        final_state = await app_graph.ainvoke(initial_state, config=config)

    retrieved_contexts, retrieved_metadata = _collect_retrieved_contexts(final_state)

    final_answer = final_state.get("final_answer") or ""
    score_summary = final_state.get("score_summary") or ""
    full_parts = [p for p in [final_answer, score_summary] if p.strip()]

    intents = final_state.get("target_intents") or []
    is_general = not intents or intents == ["general"]

    updated = dict(sample)
    updated["retrieved_contexts"] = retrieved_contexts
    llm_body = final_state.get("llm_body") or ""
    full_response = "\n\n".join(full_parts)
    if is_general:
        updated["response"] = full_response
    else:
        updated["response"] = llm_body if llm_body else "None"
    updated["full_response"] = full_response
    updated["runtime_metadata"] = {
        "thread_id": thread_id,
        "target_intents": final_state.get("target_intents") or [],
        "search_query": final_state.get("search_query") or question,
        "target_material": final_state.get("target_material"),
        "target_equipment": final_state.get("target_equipment"),
        "search_metadata": final_state.get("search_metadata") or {},
    }
    return updated


async def _run_all(
    input_path: Path,
    output_path: Path,
    intent_limits: dict[str, int | None],
) -> None:
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_samples = list(data.get("samples", []))
    selected_counts = {intent: 0 for intent in intent_limits}
    samples = []
    for s in all_samples:
        if _should_include_sample(s, intent_limits, selected_counts):
            sample_id = str(s.get("id") or "")
            intent = s.get("intent") or (sample_id.split("-", 1)[0] if "-" in sample_id else "unknown")
            selected_counts[intent] = selected_counts.get(intent, 0) + 1
            samples.append(s)

    output_samples = []
    total = len(samples)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for idx, sample in enumerate(samples, start=1):
        sample_id = str(sample.get("id") or f"sample-{idx}")
        thread_id = f"ragas_eval_{sample_id}_{timestamp}"
        updated = await _run_sample(sample=sample, thread_id=thread_id)
        output_samples.append(updated)
        print(
            f"[{idx}/{total}] {sample_id} "
            f"retrieved={len(updated.get('retrieved_contexts') or [])}"
        )

    output_data = {
        "version": data.get("version", "0.1.0"),
        "description": data.get("description", ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "samples": output_samples,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {output_path}")


def _parse_intent_limit(value: str) -> int | None:
    """N(양의 정수) 또는 'all' 파싱. all이면 None 반환."""
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


_INTENT_NOT_PROVIDED = object()


def _collect_intent_limits(args: argparse.Namespace) -> dict[str, int | None]:
    """argparse 결과에서 intent별 limit 수집. 지정된 것만 포함."""
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


def _should_include_sample(
    sample: Dict[str, Any],
    intent_limits: dict[str, int | None],
    selected_counts: dict[str, int],
) -> bool:
    """intent_limits에 따라 해당 샘플을 포함할지 판단."""
    sample_id = str(sample.get("id") or "")
    intent = sample.get("intent") or (sample_id.split("-", 1)[0] if "-" in sample_id else "unknown")
    if not intent_limits:
        return True
    if intent not in intent_limits:
        return False
    limit = intent_limits[intent]
    if limit is None:
        return True
    return selected_counts.get(intent, 0) < limit


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAGAS 평가용 실제 검색 결과/응답 채우기")
    parser.add_argument("--input", type=Path, default=None, help="입력 JSON 경로")
    parser.add_argument("--output", type=Path, default=None, help="출력 JSON 경로")
    parser.add_argument(
        "--risk",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="risk 의도 샘플만 실행. 예: --risk 30, --risk all",
    )
    parser.add_argument(
        "--law",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="law 의도 샘플만 실행. 예: --law 30, --law all",
    )
    parser.add_argument(
        "--design",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="design 의도 샘플만 실행. 예: --design 30, --design all",
    )
    parser.add_argument(
        "--general",
        type=_parse_intent_limit,
        default=_INTENT_NOT_PROVIDED,
        metavar="N|all",
        help="general 의도 샘플만 실행. 예: --general 10, --general all",
    )
    return parser.parse_args()


def _default_output_path(intent_limits: dict[str, int | None]) -> Path:
    """intent 필터에 따라 기본 출력 파일 경로 반환."""
    intent = _single_intent_for_filename(intent_limits)
    if intent:
        return RAGAS_DIR / f"ragas_test_{intent}_outputs.json"
    return RAGAS_DIR / "ragas_test_outputs.json"


if __name__ == "__main__":
    args = _parse_args()
    input_path = args.input or (RAGAS_DIR / "ragas_test.json")
    intent_limits = _collect_intent_limits(args)
    output_path = args.output or _default_output_path(intent_limits)
    asyncio.run(
        _run_all(
            input_path=input_path,
            output_path=output_path,
            intent_limits=intent_limits,
        )
    )
