from langchain_core.messages import SystemMessage, HumanMessage

from config import (
    REWRITER_MAX_TOKENS,
    REWRITER_REASONING_EFFORT,
    REWRITER_TEMPERATURE,
)
from src.core.state import AgentState
from src.core.models import VLLM_API_URL, BASE_MODEL_BF16, model_rewriter
from src.core.nodes.utils import extract_json
from src.prompts.rewriter import REWRITER_SYSTEM_PROMPT, REWRITER_USER_TEMPLATE

REWRITER_CONFIG = {
    "temperature": REWRITER_TEMPERATURE,
    "max_tokens": REWRITER_MAX_TOKENS,
}
if REWRITER_REASONING_EFFORT:
    REWRITER_CONFIG["reasoning_effort"] = REWRITER_REASONING_EFFORT

_rewrite_llm = model_rewriter.bind(**REWRITER_CONFIG)


def _none_str_to_none(value) -> str | None:
    """LLM이 출력한 "None", "null", "" 등을 Python None으로 변환"""
    if value is None:
        return None
    s = str(value).strip()
    if s in ("None", "null", "없음", ""):
        return None
    return s


def _display_entity_value(value) -> str:
    normalized = _none_str_to_none(value)
    return normalized if normalized is not None else "None"


def rewriter_node(state: AgentState):
    """
    [노드: 엔티티 추출]
    사용자 질문에서 물질명·설비명을 추출합니다.
    search_query는 사용자 질문 원문을 그대로 사용합니다.
    """
    print(">>>>> [NODE] Query Rewriter <<<<<")
    user_question = (state.get("question") or "").strip()
    prompt = REWRITER_USER_TEMPLATE.format(user_question=user_question)
    messages = [
        SystemMessage(content=REWRITER_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]
    try:
        response = _rewrite_llm.invoke(messages)
        raw = response.content or ""
    except Exception as e:
        print(f"[ERROR] Rewriter Call Failed: {e}")
        raw = ""

    parsed = extract_json(raw)

    return {
        "search_query": user_question,
        "target_material": _none_str_to_none(parsed.get("target_material")),
        "target_equipment": _none_str_to_none(parsed.get("target_equipment")),
    }


# region [rewriter 노드 테스트]
if __name__ == "__main__":
    """
    python -m src.core.nodes.rewriter --bf16

    인자:
    --bf16 / --mxfp4  : 베이스 모델 선택
    --max N           : 응답 최대 토큰 수
    --live o | i | p  : 인터랙티브 모드
    """
    import os
    import argparse
    from datetime import datetime, timezone, timedelta
    from openai import OpenAI

    from src.core.models import BASE_MODEL_MXFP4
    from tests.test_prompts.rewriter_questions import REWRITER_TEST_CASES

    CLIENT = OpenAI(base_url=VLLM_API_URL, api_key="EMPTY")

    MODEL_MAP = {"bf16": BASE_MODEL_BF16, "mxfp4": BASE_MODEL_MXFP4}
    MODELS = {
        "model_o": None,
        "model_m": "m_adapter",
    }

    LIVE_MAP = {"o": "model_o", "m": "model_m"}

    def invoke_rewriter(model_id, question, max_tokens):
        prompt = REWRITER_USER_TEMPLATE.format(
            user_question=question,
        )
        messages = [
            {"role": "system", "content": REWRITER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            resp = CLIENT.chat.completions.create(
                model=model_id, messages=messages,
                temperature=REWRITER_CONFIG["temperature"],
                max_tokens=max_tokens,
                reasoning_effort=REWRITER_CONFIG["reasoning_effort"],
            )
            if not resp.choices:
                return ""
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"\n[ERROR] {model_id}: {e}")
            return ""

    def run_test(model_name, model_id, max_tokens):
        total = len(REWRITER_TEST_CASES)
        results = []
        correct_cnt = 0
        for i, case in enumerate(REWRITER_TEST_CASES):
            question = case["user_question"]
            lbl_mat = _none_str_to_none(case["label_material"])
            lbl_eq = _none_str_to_none(case["label_equipment"])
            raw = invoke_rewriter(model_id, question, max_tokens)
            parsed = extract_json(raw)
            pred_mat = _none_str_to_none(parsed.get("target_material"))
            pred_eq = _none_str_to_none(parsed.get("target_equipment"))
            mat_ok = pred_mat == lbl_mat
            eq_ok = pred_eq == lbl_eq
            correct = mat_ok and eq_ok
            if correct:
                correct_cnt += 1
            results.append({
                "idx": i + 1, "user_question": question,
                "label_material": _display_entity_value(lbl_mat),
                "label_equipment": _display_entity_value(lbl_eq),
                "pred_material": _display_entity_value(pred_mat),
                "pred_equipment": _display_entity_value(pred_eq),
                "mat_ok": mat_ok, "eq_ok": eq_ok,
                "correct": correct, "raw": raw,
            })
            pct = (i + 1) / total * 100
            print(f"\r  [{i+1:3d}/{total}] {pct:5.1f}% (정답 {correct_cnt}개)", end="", flush=True)
        print()
        return results

    def calc_accuracy(results):
        total = len(results)
        mat_correct = sum(1 for r in results if r["mat_ok"])
        eq_correct = sum(1 for r in results if r["eq_ok"])
        both_correct = sum(1 for r in results if r["correct"])
        return {
            "material": {"correct": mat_correct, "total": total,
                         "accuracy": mat_correct / total * 100 if total else 0.0},
            "equipment": {"correct": eq_correct, "total": total,
                          "accuracy": eq_correct / total * 100 if total else 0.0},
            "overall": {"correct": both_correct, "total": total,
                        "accuracy": both_correct / total * 100 if total else 0.0},
        }

    def build_report(all_model_results, timestamp):
        lines = []
        sep = "=" * 70
        sub_sep = "-" * 70

        lines.append(sep)
        lines.append("REWRITER ENTITY EXTRACTION - ACCURACY REPORT")
        lines.append(f"Timestamp: {timestamp}")
        lines.append(f"Total questions: {len(REWRITER_TEST_CASES)}")
        lines.append(sep)
        lines.append("REWRITER TEST RESULTS")

        model_names = list(all_model_results.keys())

        def fmt_score(s):
            return f"{s['correct']:>3}/{s['total']:<3} ({s['accuracy']:>5.1f}%)"

        for field in ["material", "equipment"]:
            parts = []
            for mn in model_names:
                s = all_model_results[mn]["stats"][field]
                parts.append(f"[{mn}] {fmt_score(s)}")
            lines.append(f"{field:<12} {' | '.join(parts)}")

        lines.append(sub_sep)
        parts = []
        for mn in model_names:
            s = all_model_results[mn]["stats"]["overall"]
            parts.append(f"[{mn}] {fmt_score(s)}")
        lines.append(f"{'OVERALL':<12} {' | '.join(parts)}")
        lines.append(sep)
        lines.append("")

        for mn in model_names:
            wrong = [r for r in all_model_results[mn]["results"] if not r["correct"]]
            if wrong:
                nums = ", ".join(f"{r['idx']:03d}" for r in wrong)
                lines.append(f"[{mn}] 오답({len(wrong)}개): {nums}")
            else:
                lines.append(f"[{mn}] 오답 없음")
        lines.append("")
        lines.append("")

        lines.append(sep)
        lines.append("DETAILED RESPONSES")
        lines.append(sep)
        lines.append("")

        for i, case in enumerate(REWRITER_TEST_CASES):
            question = case["user_question"]
            lbl_mat = _display_entity_value(case["label_material"])
            lbl_eq = _display_entity_value(case["label_equipment"])
            lines.append(f"[Q{i+1:03d}] {question}")
            lines.append(f"  정답: material={lbl_mat}, equipment={lbl_eq}")
            lines.append("")
            for model_name, data in all_model_results.items():
                r = data["results"][i]
                mat_mark = "O" if r["mat_ok"] else "X"
                eq_mark = "O" if r["eq_ok"] else "X"
                lines.append(f"  [{model_name}] material={r['pred_material']} [{mat_mark}] | equipment={r['pred_equipment']} [{eq_mark}]")
                raw_oneline = r["raw"].replace("\n", " ")
                lines.append(f"    응답: {raw_oneline}")
            lines.append("")
            lines.append(sub_sep)

        return "\n".join(lines)

    def live_mode(model_name, model_id, max_tokens):
        sep = "=" * 60
        print(sep)
        print(f"Model: {model_name}")
        print(sep)
        while True:
            try:
                user_input = input("[user_question]\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.lower() in ("q", "quit", "exit", "ㅂ"):
                break
            if not user_input:
                continue
            prompt = REWRITER_USER_TEMPLATE.format(
                user_question=user_input,
            )
            messages = [
                {"role": "system", "content": REWRITER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            resp = CLIENT.chat.completions.create(
                model=model_id, messages=messages,
                temperature=REWRITER_CONFIG["temperature"],
                max_tokens=max_tokens,
                reasoning_effort=REWRITER_CONFIG["reasoning_effort"],
            )
            msg = resp.choices[0].message
            content = (msg.content or "").strip()
            reasoning = (
                getattr(msg, "reasoning", None)
                or getattr(msg, "reasoning_content", None)
                or ""
            ).strip()
            if reasoning:
                print(f"\n[reasoning]\n> {reasoning[:2000]}")
            print(f"\n[rewriter answer]\n> {content if content else '(empty)'}")
            print("")
            print(sep)

    def parse_args():
        parser = argparse.ArgumentParser(
            description="REWRITER ENTITY EXTRACTION TEST",
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--bf16", action="store_true", help="USE BF16 BASE MODEL")
        group.add_argument("--mxfp4", action="store_true", help="USE MXFP4 QUANTIZED MODEL")
        parser.add_argument("--max", type=int, default=REWRITER_CONFIG["max_tokens"], help="MAX TOKENS")
        parser.add_argument("--models", choices=["all", "o", "m"], default="all", help="TEST MODEL SET")
        parser.add_argument("--live", choices=["o", "m"], default=None, help="INTERACTIVE MODE")
        return parser.parse_args()

    def main():
        args = parse_args()
        quant = "bf16" if args.bf16 else "mxfp4"
        MODELS["model_o"] = MODEL_MAP[quant]

        if args.live:
            name = LIVE_MAP[args.live]
            live_mode(name, MODELS[name], args.max)
            return

        selected_models = dict(MODELS)
        if args.models == "o":
            selected_models = {"model_o": MODELS["model_o"]}
        elif args.models == "m":
            selected_models = {"model_m": MODELS["model_m"]}

        KST = timezone(timedelta(hours=9))
        now = datetime.now(KST)
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        output_dir = os.path.join("tests", "test_rewriter")
        os.makedirs(output_dir, exist_ok=True)

        print("=" * 60)
        print(f"BASE MODEL: {quant}")
        print(f"MAX TOKENS: {args.max}")
        print(f"RESULT SAVE PATH: {output_dir}")
        print(f"TEST START TIME: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        all_model_results = {}
        for model_name, model_id in selected_models.items():
            print(f"\n{'='*60}")
            print(f"[{model_name}] TEST START")
            print(f"{'='*60}")
            results = run_test(model_name, model_id, args.max)
            stats = calc_accuracy(results)
            print(f"\n[{model_name}] REWRITER TEST RESULTS:")
            for field in ["material", "equipment"]:
                s = stats[field]
                print(f"- {field}: {s['correct']}/{s['total']} ({s['accuracy']:.1f}%)")
            s = stats["overall"]
            print(f"- OVERALL: {s['correct']}/{s['total']} ({s['accuracy']:.1f}%)")
            all_model_results[model_name] = {"results": results, "stats": stats}

        filename = f"rewriter_extract_{timestamp}.txt"
        filepath = os.path.join(output_dir, filename)
        report = build_report(all_model_results, timestamp)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"\n{'='*60}")
        print(f"TEST COMPLETE TIME: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"RESULT SAVE PATH: {filepath}")

    main()
# endregion [rewriter 노드 테스트]