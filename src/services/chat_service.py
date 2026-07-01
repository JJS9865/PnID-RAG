from pathlib import Path
from typing import Any, Dict, Optional

from config import FASTAPI_BASE_URL
from src.core.graph import app_graph
from src.core.state import AgentState
from src.services.json_parser import facility_json_to_text

CORPUS_DIR = Path(__file__).resolve().parents[2] / "data" / "corpus"
ACCIDENTS_PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "accidents_pdf"
CORPUS_PATH_PREFIX = "./data/corpus/"
STATIC_URL_PREFIX = f"{FASTAPI_BASE_URL}/static/corpus/"
ACCIDENTS_PDF_URL_PREFIX = f"{FASTAPI_BASE_URL}/static/accidents_pdf/"


def _to_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _encode_all_bytes(value: str) -> str:
    """UTF-8 바이트를 모두 %HH 형식으로 인코딩."""
    return "".join(f"%{byte:02X}" for byte in value.encode("utf-8"))


def _format_score_parts(doc: Dict[str, Any]) -> str:
    parts = []

    primary_score = _to_optional_float(doc.get("primary_score"))
    if primary_score is not None:
        parts.append(f"1차={primary_score:.4f}")

    rerank_score = _to_optional_float(doc.get("rerank_score"))
    if rerank_score is not None:
        parts.append(f"2차={rerank_score:.4f}")

    score = _to_optional_float(doc.get("score"))
    if not parts and score is not None:
        parts.append(f"score={score:.4f}")

    return ", ".join(parts)


_corpus_rel_cache: Dict[str, Optional[str]] = {}


def _resolve_corpus_rel(source_path: str) -> Optional[str]:
    """DB source_path → 실제 파일시스템 기준 상대경로 반환 (CORPUS_DIR 기준)"""
    if source_path in _corpus_rel_cache:
        return _corpus_rel_cache[source_path]

    result = None
    if source_path.startswith(CORPUS_PATH_PREFIX):
        rel = source_path[len(CORPUS_PATH_PREFIX):]
    elif source_path.startswith("data/corpus/"):
        rel = source_path[len("data/corpus/"):]
    else:
        _corpus_rel_cache[source_path] = None
        return None

    real = CORPUS_DIR / rel
    if real.is_file():
        result = rel
    else:
        parent = real.parent
        if parent.is_dir():
            db_stem = real.stem.lower()
            for candidate in parent.iterdir():
                if candidate.suffix.lower() != ".pdf":
                    continue
                if candidate.stem.lower().replace("'", "_") == db_stem:
                    result = str(candidate.relative_to(CORPUS_DIR))
                    break

    _corpus_rel_cache[source_path] = result
    return result


def _build_accident_pdf_url(doc: Dict[str, Any]) -> Optional[str]:
    doc_id = _to_optional_str(doc.get("doc_id") or doc.get("id"))
    if not doc_id:
        return None
    filename = f"{doc_id}.pdf"
    pdf_path = ACCIDENTS_PDF_DIR / filename
    if not pdf_path.is_file():
        return None
    return f"{ACCIDENTS_PDF_URL_PREFIX}{_encode_all_bytes(filename)}"


def _build_pdf_url(doc: Dict[str, Any]) -> Optional[str]:
    source_path = _to_optional_str(doc.get("source_path"))
    if not source_path:
        return None
    if not source_path.lower().endswith(".pdf"):
        return _build_accident_pdf_url(doc)
    rel = _resolve_corpus_rel(source_path)
    if not rel:
        return None
    encoded = "/".join(_encode_all_bytes(seg) for seg in rel.split("/"))
    url = f"{STATIC_URL_PREFIX}{encoded}"
    page = _to_optional_int(doc.get("page"))
    if page is not None:
        url += f"#page={page}"
    return url


def _build_sources(final_state: dict) -> list:
    """검색된 문서(docs)를 API 응답용 sources 리스트로 변환"""
    doc_keys = [
        "accident_docs",
        "chemical_docs",
        "law_docs",
        "design_docs",
    ]
    sources = []
    for state_key in doc_keys:
        docs = final_state.get(state_key) or []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            chunk_text = _to_optional_str(doc.get("chunk_text") or doc.get("text"))
            if not chunk_text:
                continue
            rerank_score = _to_optional_float(doc.get("rerank_score"))
            sources.append({
                "doc_id": _to_optional_str(doc.get("doc_id") or doc.get("id")),
                "title": _to_optional_str(doc.get("title") or doc.get("source")),
                "page": _to_optional_int(doc.get("page")),
                "chunk_text": chunk_text[:500],
                "score": rerank_score,
                "primary_score": _to_optional_float(doc.get("primary_score")),
                "rerank_score": rerank_score,
                "pdf_url": _build_pdf_url(doc),
            })
    return sources


def _build_initial_state(question: str, facility_text: str) -> AgentState:
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
        "score_summary": "",
    }


def _prepare_facility_text(facility_info: Dict[str, Any]) -> str:
    if not facility_info:
        return ""

    return facility_json_to_text(facility_info).strip()


async def chat(thread_id: str, user_message: str, facility_info: Dict[str, Any]) -> dict:
    """
    API 요청을 처리하는 chat_service 공개 엔트리포인트

    Args:
        thread_id: LangGraph 메모리 식별자
        user_message: 사용자 질문
        facility_info: P&ID JSON 원본

    Returns:
        {"answer": str, "sources": list}
    """
    facility_text = _prepare_facility_text(facility_info)
    return await run_chat(
        thread_id=thread_id,
        question=(user_message or "").strip(),
        facility_text=facility_text,
    )


async def run_chat(thread_id: str, question: str, facility_text: str) -> dict:
    """
    app_graph를 실행하고 최종 답변을 반환합니다.

    Args:
        thread_id: LangGraph 메모리 식별자 (대화 이력 관리용)
        question: 사용자 질문
        facility_text: json_parser로 변환된 설비 텍스트

    Returns:
        {"answer": str, "sources": list}
    """
    initial_state = _build_initial_state(
        question=(question or "").strip(),
        facility_text=(facility_text or "").strip(),
    )
    config = {"configurable": {"thread_id": thread_id}}

    final_state = await app_graph.ainvoke(initial_state, config=config)

    return {
        "answer": final_state.get("final_answer") or "",
        "sources": _build_sources(final_state),
    }



# chat_service 테스트용
"""
python -m src.services.chat_service --question "톨루엔을 취급하는 반응기에서 압력 상승이나 누출이 발생할 때 어떤 공정 위험이 있는지 설명해줘." --facility-path "src/prompts/dummy_facility_info.json"
"""
if __name__ == "__main__":
    import asyncio
    import json
    import re
    import sys
    import time
    import traceback
    from contextlib import redirect_stderr, redirect_stdout
    from copy import deepcopy
    from datetime import datetime
    from pathlib import Path
    from typing import Callable
    from src.core.models import shutdown_search_models
    from src.prompts.dummy_facility_info import DUMMY_FACILITY

    def _merge_state_update(state: AgentState, update: Dict[str, Any]) -> None:
        for key, value in update.items():
            if key == "partial_answers":
                existing = list(state.get("partial_answers") or [])
                incoming = list(value or [])
                state["partial_answers"] = existing + incoming
                continue
            if key == "node_outputs":
                merged = dict(state.get("node_outputs") or {})
                merged.update(dict(value or {}))
                state["node_outputs"] = merged
                continue
            state[key] = deepcopy(value)

    def _next_step_from_intents(intents: Any) -> str:
        intents = intents or []
        if len(intents) > 1:
            return "multi_intent_clarify"
        if any(intent in intents for intent in ("risk", "law", "design")):
            return "retriever"
        return "fallback"

    def _indent_block(text: str, prefix: str = "") -> str:
        return "\n".join(f"{prefix}{line}" if line else prefix.rstrip() for line in text.splitlines())

    def _preview_text(text: Any, limit: Optional[int] = 1200) -> str:
        if text is None:
            return "None"
        value = str(text).strip()
        if not value:
            return "None"
        if limit is None or len(value) <= limit:
            return value
        return value[:limit].rstrip() + "\n... (truncated)"

    def _format_json_block(data: Any) -> str:
        try:
            return json.dumps(data, ensure_ascii=False, indent=2)
        except TypeError:
            return str(data)

    def _format_section_header(title: str, sep: str = "=") -> str:
        line = sep * 70
        return f"{line}\n{title}\n{line}"

    def _format_doc_summary(docs: list, limit: Optional[int] = None) -> str:
        lines = [f"문서 수: {len(docs)}"]
        docs_to_show = docs if limit is None else docs[:limit]
        for idx, doc in enumerate(docs_to_show, 1):
            if not isinstance(doc, dict):
                lines.append(f"▶ 문서 {idx}: {_preview_text(doc, limit=300)}")
                continue
            lines.append(f"▶ 문서 {idx}")
            lines.append(f"  doc_id: {_to_optional_str(doc.get('doc_id') or doc.get('id'))}")
            lines.append(f"  title: {_to_optional_str(doc.get('title') or doc.get('source'))}")
            score_parts = _format_score_parts(doc)
            if score_parts:
                lines.append(f"  scores: {score_parts}")
            lines.append(f"  page: {_to_optional_int(doc.get('page'))}")
            lines.append(f"  pdf_url: {_to_optional_str(doc.get('pdf_url'))}")
            if _to_optional_str(doc.get("material")) is not None:
                lines.append(f"  material: {_to_optional_str(doc.get('material'))}")
            if _to_optional_str(doc.get("equipment")) is not None:
                lines.append(f"  equipment: {_to_optional_str(doc.get('equipment'))}")
            lines.append(f"  text: {_preview_text(doc.get('text') or doc.get('chunk_text'), limit=500)}")
        return "\n".join(lines)

    def _format_node_trace(node_name: str, update: Dict[str, Any], state: AgentState) -> str:
        lines = []

        if node_name == "rewriter":
            lines.append(f"▶ search_query: {_preview_text(update.get('search_query'), limit=1000)}")
            lines.append(f"▶ target_material: {_to_optional_str(update.get('target_material'))}")
            lines.append(f"▶ target_equipment: {_to_optional_str(update.get('target_equipment'))}")
            return "\n".join(lines)

        if node_name == "router":
            intents = update.get("target_intents") or []
            lines.append(f"▶ target_intents: {intents}")
            # lines.append(f"▶ next_step: {_next_step_from_intents(intents)}")
            return "\n".join(lines)

        if node_name == "retriever":
            lines.append(f"▶ query: {_preview_text(state.get('search_query') or state.get('question'), limit=1000)}")
            lines.append(
                f"▶ filters: material={_to_optional_str(state.get('target_material'))}, "
                f"equipment={_to_optional_str(state.get('target_equipment'))}"
            )
            lines.append(f"▶ search_metadata: {_format_json_block(update.get('search_metadata') or {})}")
            for key in ("accident_docs", "chemical_docs", "law_docs", "design_docs"):
                docs = update.get(key) or []
                lines.append(f"▶ {key}:")
                lines.append(_indent_block(_format_doc_summary(docs)))
            return "\n".join(lines)

        node_key_map = {
            "chemical_node": "chemical",
            "accident_node": "accident",
            "law_node": "law",
            "design_node": "design",
        }
        if node_name in node_key_map:
            node_key = node_key_map[node_name]
            node_outputs = update.get("node_outputs") or {}
            lines.append(f"▶ partial_answers_added: {len(update.get('partial_answers') or [])}")
            lines.append(f"▶ node_key: {node_key}")
            lines.append("▶ node_output:")
            lines.append(_indent_block(_preview_text(node_outputs.get(node_key), limit=None)))
            return "\n".join(lines)

        if node_name in ("generator", "fallback", "multi_intent_clarify"):
            answer = (update.get("final_answer") or "").rstrip()
            score_summary = (update.get("score_summary") or "").strip()
            if score_summary:
                display = f"{answer}\n\n---\n\n{score_summary}"
            else:
                display = answer
            lines.append("▶ final_answer:")
            lines.append(_indent_block(_preview_text(display, limit=None)))
            return "\n".join(lines)

        lines.append(_format_json_block(update))
        return "\n".join(lines)

    def _write_blank_lines(log_func: Optional[Callable[[str], None]], count: int = 5) -> None:
        if not log_func:
            return
        for _ in range(count):
            log_func("")

    async def run_chat_with_trace(
        thread_id: str,
        question: str,
        facility_info: Dict[str, Any],
        log_func: Optional[Callable[[str], None]] = None,
    ) -> dict:
        facility_text = _prepare_facility_text(facility_info)
        initial_state = _build_initial_state(
            question=(question or "").strip(),
            facility_text=facility_text,
        )
        config = {"configurable": {"thread_id": thread_id}}
        merged_state: AgentState = deepcopy(initial_state)
        started_at = time.perf_counter()
        event_count = 0

        if log_func:
            log_func(_format_section_header("INPUT"))
            log_func(f"▶ thread_id: {thread_id}")
            log_func(f"▶ user_question: {_preview_text(question, limit=2000)}")
            log_func("▶ facility_json:")
            log_func(_indent_block(_format_json_block(facility_info)))
            log_func("▶ facility_text:")
            log_func(_indent_block(_preview_text(facility_text or "(empty)", limit=None)))
            _write_blank_lines(log_func, count=5)

        async for chunk in app_graph.astream(initial_state, config=config, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue

            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue

                event_count += 1
                _merge_state_update(merged_state, update)

                if log_func:
                    elapsed = time.perf_counter() - started_at
                    log_func(_format_section_header(f"TRACE {event_count:02d}. {node_name.upper()} (+{elapsed:.2f}s)"))
                    log_func(_format_node_trace(node_name, update, merged_state))
                    _write_blank_lines(log_func, count=5)

        result = {
            "answer": merged_state.get("final_answer") or "",
            "sources": _build_sources(merged_state),
            "final_state": merged_state,
            "facility_text": facility_text,
        }

        return result

    class _Tee:
        _node_banner_pattern = re.compile(r">>>>> \[NODE\][^\n]*<<<<<")

        def __init__(self, *streams):
            self.streams = streams
            self._suppress_next_newline = False

        def write(self, data):
            if self._suppress_next_newline and data == "\n":
                self._suppress_next_newline = False
                return len(data)

            if self._node_banner_pattern.fullmatch(data.strip()):
                self._suppress_next_newline = True
                return len(data)

            self._suppress_next_newline = False
            filtered = self._node_banner_pattern.sub("", data)
            if not filtered:
                return len(data)
            for stream in self.streams:
                stream.write(filtered)
                stream.flush()
            return len(data)

        def flush(self):
            for stream in self.streams:
                stream.flush()

    def _parse_args():
        import argparse

        parser = argparse.ArgumentParser(description="chat_service 실행 추적")
        parser.add_argument("--question", type=str, default="", help="사용자 질문")
        parser.add_argument("--facility-path", type=str, default="", help="설비 JSON 파일 경로")
        parser.add_argument("--facility-json", type=str, default="", help="설비 JSON 문자열")
        parser.add_argument("--thread-id", type=str, default="", help="thread_id")
        parser.add_argument("--use-dummy", action="store_true", help="내장 더미 설비 JSON 사용")
        return parser.parse_args()

    def _load_facility_info(args) -> Dict[str, Any]:
        if args.use_dummy:
            return json.loads(DUMMY_FACILITY)

        if args.facility_path:
            path = Path(args.facility_path)
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        if args.facility_json:
            return json.loads(args.facility_json)

        return {}

    async def _main():
        args = _parse_args()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        thread_id = args.thread_id or f"chat_service_trace_{timestamp}"
        question = (args.question or input("[질문] ").strip()).strip()
        facility_info = _load_facility_info(args)
        output_dir = Path(__file__).resolve().parents[2] / "tests" / "test_chat_service"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / f"chat_service_trace_{timestamp}.txt"

        with open(log_path, "w", encoding="utf-8") as log_file:
            tee = _Tee(sys.stdout, log_file)
            with redirect_stdout(tee), redirect_stderr(tee):
                # print(_format_section_header("CHAT SERVICE TRACE"))
                # print(f"▶ 로그 파일: {log_path}")
                # print(f"▶ 시작 시각: {timestamp}")
                # print("\n\n\n\n")
                try:
                    await run_chat_with_trace(
                        thread_id=thread_id,
                        question=question,
                        facility_info=facility_info,
                        log_func=print,
                    )
                except Exception:
                    print("[ERROR] 실행 중 예외가 발생했습니다.")
                    print(traceback.format_exc())
                    raise
                finally:
                    try:
                        shutdown_search_models()
                    except Exception as cleanup_error:
                        print(f"[WARN] 검색 모델 풀 정리 실패: {cleanup_error}")

    asyncio.run(_main())
