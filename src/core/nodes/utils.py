import json
import re
from typing import List

from src.core.models import model_llm

llm = model_llm


def extract_json(text: str) -> dict:
    """
    LLM 응답 텍스트에서 JSON 객체를 추출하여 딕셔너리로 변환합니다.

    동작 순서:
    1. 마크다운 코드 블록(```json ... ```) 내부의 내용을 우선적으로 탐색합니다.
    2. 실패 시, 텍스트 전체에서 중괄호({ ... })로 묶인 영역을 탐색합니다.
    3. JSON 파싱 에러가 발생하거나 매칭되는 패턴이 없으면 빈 딕셔너리({})를 반환합니다.
    """
    if not text:
        return {}

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    return {}


def meta_bool(val) -> str:
    """
    Python의 불리언 값(True/False)이나 존재 여부를
    LLM 프롬프트에 텍스트로 삽입하기 위해 'YES' 또는 'NO' 문자열로 변환합니다.
    """
    return "YES" if val else "NO"


def scored_docs_to_context(docs: list) -> str:
    """
    검색된 문서(딕셔너리 리스트)를 LLM이 이해하기 쉬운 문자열 포맷으로 변환합니다.

    입력 예시: [{'text': '내용...', 'score': 0.9}, ...]
    출력 예시: "[CITE_1]\n문서 제목: example.pdf\n유사도: 0.9\n본문:\n내용..."
    """
    if not docs:
        return ""
    lines = []
    for i, item in enumerate(docs, 1):
        if isinstance(item, dict):
            text = item.get("text", "")
            score = item.get("score", 0)
            title = (
                item.get("title")
                or item.get("source")
                or item.get("doc_id")
                or item.get("id")
                or "제목 없음"
            )
            doc_id = item.get("doc_id") or item.get("id") or "없음"
            page = item.get("page")
            page_text = str(page) if page not in (None, "") else "없음"
            lines.append(
                f"[CITE_{i}]\n"
                f"문서 제목: {title}\n"
                f"문서 ID: {doc_id}\n"
                f"페이지: {page_text}\n"
                f"유사도: {score}\n"
                "본문:\n"
                f"{text}"
            )
        else:
            lines.append(str(item))
    return "\n\n".join(lines)


def collect_doc_titles(docs: list) -> List[str]:
    """검색 결과에서 중복 없는 문서 제목 목록을 순서대로 추출"""
    titles: List[str] = []
    seen = set()
    for item in docs or []:
        if not isinstance(item, dict):
            continue
        title = (
            item.get("title")
            or item.get("source")
            or item.get("doc_id")
            or item.get("id")
            or "제목 없음"
        )
        if title in seen:
            continue
        seen.add(title)
        titles.append(str(title))
    return titles


def build_reference_header(docs: list) -> str:
    """노드 출력 상단에 붙일 참고 문서 목록 생성"""
    titles = collect_doc_titles(docs)
    if not titles:
        return ""
    lines = ["[참고 문서]"]
    lines.extend(f"- {title}" for title in titles)
    return "\n".join(lines)


def format_node_output(text: str, docs: list) -> str:
    """노드 본문을 정리하고 상단에 참고 문서 목록을 추가"""
    cleaned = (text or "").strip()
    header = build_reference_header(docs)
    if header and cleaned:
        return f"{header}\n\n{cleaned}".strip()
    return cleaned or header


def has_usable_docs(docs: list) -> bool:
    """
    검색된 문서 리스트가 분석에 사용할 수 있는 유효한 데이터를 포함하는지 검사합니다.

    기준:
    1. 리스트가 비어있지 않아야 함.
    2. 딕셔너리 형태인 경우 'text' 필드에 내용이 있어야 함.
    """
    if not docs:
        return False
    for d in docs:
        if isinstance(d, dict):
            if d.get("text"):
                return True
        else:
            return True
    return False
