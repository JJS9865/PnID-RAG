from langchain_core.messages import SystemMessage, HumanMessage

from config import (
    ROUTER_MAX_TOKENS,
    ROUTER_REASONING_EFFORT,
    ROUTER_TEMPERATURE,
)
from src.core.state import AgentState
from src.core.models import VLLM_API_URL, BASE_MODEL_BF16, model_router
from src.core.nodes.utils import extract_json
from src.prompts.router import ROUTER_SYSTEM_PROMPT


ROUTER_CONFIG = {
    "temperature": ROUTER_TEMPERATURE,
    "max_tokens": ROUTER_MAX_TOKENS,
}
if ROUTER_REASONING_EFFORT:
    ROUTER_CONFIG["reasoning_effort"] = ROUTER_REASONING_EFFORT

_router_llm = model_router.bind(**ROUTER_CONFIG)


def _parse_intent(raw: str):
    """모델 응답에서 intent를 추출하고 파싱된 JSON을 함께 반환"""
    parsed = extract_json(raw)
    intents = parsed.get("intents", parsed.get("intent", []))
    if isinstance(intents, str):
        return intents, parsed
    if isinstance(intents, list) and len(intents) == 1:
        return intents[0], parsed
    return "general", parsed


def router_node(state: AgentState):
    """
    [노드: 라우터]
    LLM을 사용하여 사용자 의도를 분석하고,
    이후 실행할 분석 노드(risk, law, design, general)를 결정합니다.
    """
    print(">>>>> [NODE] Router <<<<<")
    messages = [
        SystemMessage(content=ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=state.get("question", "")),
    ]
    try:
        response = _router_llm.invoke(messages)
        raw = response.content or ""
    except Exception as e:
        print(f"[ERROR] Router Call Failed: {e}")
        raw = ""
    intent, _ = _parse_intent(raw)
    return {"target_intents": [intent]}


# region [router 노드 테스트]
if __name__ == "__main__":
    """
    python -m src.core.nodes.router --bf16 --max 128 --live o

    인자:
    --bf16 / --mxfp4  : 베이스 모델 선택
    --max N           : 응답 최대 토큰 수
    --live o | i | p  : 인터랙티브 모드

    # 분류기 성능이 낮다면 의심해 볼 수 있는 이유들
    1) 분류기 전용 학습 데이터셋이 없어서?
    2) 학습 데이터가 3개 카테고리 전부 완성되지 않아서?
    3) 학습 데이터가 정제되지 않아서? 
    4) 추론 토큰 사용량이 많아 max token이 부족해서?

    """
    import os
    import argparse
    from datetime import datetime, timezone, timedelta
    from openai import OpenAI

    from src.core.models import BASE_MODEL_MXFP4
    from tests.test_prompts.router_questions import ROUTER_TEST_CASES

    CLIENT = OpenAI(base_url=VLLM_API_URL, api_key="EMPTY")

    MODEL_MAP = {"bf16": BASE_MODEL_BF16, "mxfp4": BASE_MODEL_MXFP4}
    MODELS = {
        "model_o": None,
        "model_m": "m_adapter",
    }

    CATEGORIES = ["risk", "law", "design", "general"]
    CATEGORY_LABELS = {
        "risk": "공정위험성",
        "law": "법규위반",
        "design": "설계오류",
        "general": "일반대화",
    }

    LIVE_MAP = {"o": "model_o", "m": "model_m"}

    def invoke_router(model_id, question, max_tokens):
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        try:
            resp = CLIENT.chat.completions.create(
                model=model_id, messages=messages,
                temperature=ROUTER_CONFIG["temperature"],
                max_tokens=max_tokens,
                reasoning_effort=ROUTER_CONFIG["reasoning_effort"],
            )
            if not resp.choices:
                return ""
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"\n[ERROR] {model_id}: {e}")
            return ""

    def run_test(model_name, model_id, max_tokens):
        total = len(ROUTER_TEST_CASES)
        results = []
        correct_cnt = 0
        for i, case in enumerate(ROUTER_TEST_CASES):
            q, label = case["question"], case["label"]
            raw = invoke_router(model_id, q, max_tokens)
            predicted, _ = _parse_intent(raw)
            correct = predicted == label
            if correct:
                correct_cnt += 1
            results.append({
                "idx": i + 1, "question": q, "label": label,
                "predicted": predicted, "raw": raw, "correct": correct,
            })
            pct = (i + 1) / total * 100
            print(f"\r  [{i+1:3d}/{total}] {pct:5.1f}% (정답 {correct_cnt}개)", end="", flush=True)
        print()
        return results

    def calc_accuracy(results):
        stats = {}
        for cat in CATEGORIES:
            cat_results = [r for r in results if r["label"] == cat]
            cat_correct = sum(1 for r in cat_results if r["correct"])
            total = len(cat_results)
            stats[cat] = {
                "correct": cat_correct, "total": total,
                "accuracy": cat_correct / total * 100 if total > 0 else 0.0,
            }
        all_correct = sum(1 for r in results if r["correct"])
        all_total = len(results)
        stats["overall"] = {
            "correct": all_correct, "total": all_total,
            "accuracy": all_correct / all_total * 100 if all_total > 0 else 0.0,
        }
        return stats

    def build_report(all_model_results, timestamp):
        lines = []
        sep = "=" * 70
        sub_sep = "-" * 70

        lines.append(sep)
        lines.append("ROUTER INTENT CLASSIFICATION - ACCURACY REPORT")
        lines.append(f"Timestamp: {timestamp}")
        lines.append(f"Total questions: {len(ROUTER_TEST_CASES)}")
        lines.append(sep)
        lines.append("ROUTER TEST RESULTS")

        model_names = list(all_model_results.keys())

        def fmt_score(s):
            return f"{s['correct']:>3}/{s['total']:<3} ({s['accuracy']:>5.1f}%)"

        for cat in CATEGORIES:
            parts = []
            for mn in model_names:
                s = all_model_results[mn]["stats"][cat]
                parts.append(f"[{mn}] {fmt_score(s)}")
            lines.append(f"{cat:<10} {' | '.join(parts)}")

        lines.append(sub_sep)
        parts = []
        for mn in model_names:
            s = all_model_results[mn]["stats"]["overall"]
            parts.append(f"[{mn}] {fmt_score(s)}")
        lines.append(f"{'OVERALL':<10} {' | '.join(parts)}")
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

        for i, case in enumerate(ROUTER_TEST_CASES):
            q, label = case["question"], case["label"]
            lines.append(f"[Q{i+1:03d}] {q}")
            lines.append(f"  정답: {label}")
            lines.append("")
            for model_name, data in all_model_results.items():
                r = data["results"][i]
                mark = "O" if r["correct"] else "X"
                lines.append(f"  [{model_name}] 예측={r['predicted']} [{mark}]")
                raw_oneline = r["raw"].replace("\n", " ")[:120]
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
                user_input = input("[query]\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.lower() in ("q", "quit", "exit", "ㅂ"):
                break
            if not user_input:
                continue
            messages = [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ]
            resp = CLIENT.chat.completions.create(
                model=model_id, messages=messages,
                temperature=ROUTER_CONFIG["temperature"],
                max_tokens=max_tokens,
                reasoning_effort=ROUTER_CONFIG["reasoning_effort"],
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
            print(f"\n[router answer]\n> {content if content else '(empty)'}")
            print("")
            print(sep)

    def parse_args():
        parser = argparse.ArgumentParser(
            description="ROUTER INTENT CLASSIFICATION TEST",
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--bf16", action="store_true", help="USE BF16 BASE MODEL")
        group.add_argument("--mxfp4", action="store_true", help="USE MXFP4 QUANTIZED MODEL")
        parser.add_argument("--max", type=int, default=ROUTER_CONFIG["max_tokens"], help="MAX TOKENS")
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

        output_dir = os.path.join("tests", "test_router")
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
            print(f"\n[{model_name}] ROUTER TEST RESULTS:")
            for cat in CATEGORIES:
                s = stats[cat]
                print(f"- {cat}: {s['correct']}/{s['total']} ({s['accuracy']:.1f}%)")
            s = stats["overall"]
            print(f"- OVERALL: {s['correct']}/{s['total']} ({s['accuracy']:.1f}%)")
            all_model_results[model_name] = {"results": results, "stats": stats}

        filename = f"router_intents_{timestamp}.txt"
        filepath = os.path.join(output_dir, filename)
        report = build_report(all_model_results, timestamp)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"\n{'='*60}")
        print(f"TEST COMPLETE TIME: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"RESULT SAVE PATH: {filepath}")

    main()
# endregion [router 노드 테스트]