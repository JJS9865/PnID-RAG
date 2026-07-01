import re
from concurrent.futures import ThreadPoolExecutor
from typing import List

from langchain_core.messages import SystemMessage, HumanMessage

from src.core.state import AgentState
from src.core.nodes.utils import (
    llm,
    has_usable_docs,
    scored_docs_to_context,
)
from src.prompts.fallback import ERROR_RESPONSE, MULTI_INTENT_RESPONSE
from src.prompts.check_risks import (
    get_risk_final_prompt,
    get_risk_explain_prompt,
    get_risk_cases_prompt,
)
from src.prompts.check_laws import (
    LAW_CASE_SELECTOR_SYSTEM_PROMPT,
    LAW_CASE_SELECTOR_USER_TEMPLATE,
    get_law_final_prompt,
)
from src.prompts.check_designs import (
    DESIGN_CASE_SELECTOR_SYSTEM_PROMPT,
    DESIGN_CASE_SELECTOR_USER_TEMPLATE,
    get_design_final_prompt,
)


NO_EVIDENCE_RISK = "검색된 근거 문서가 없어 공정위험성에 대한 답변을 드릴 수 없습니다."
NO_EVIDENCE_LAW = "검색된 근거 문서가 없어 법규위반에 대한 답변을 드릴 수 없습니다."
NO_EVIDENCE_DESIGN = "검색된 근거 문서가 없어 설계오류에 대한 답변을 드릴 수 없습니다."

LAW_FIXED_INTROS = {
    "2-1": "검색된 문서를 기준으로 검토한 결과, 법적 요구사항을 충족하지 않는 것으로 확인되었습니다.",
    "2-2": "검색된 문서를 기준으로 검토한 결과, 법적 요구사항을 충족하는 것으로 확인되었습니다.",
    "2-3": "검색된 문서를 기준으로 검토한 결과, 현재 설비 정보만으로는 법규위반 여부를 명확히 판단하기 어렵습니다.",
}

LAW_FIXED_OUTROS = {
    "2-1": "해당 조항 위반 시 과태료 또는 행정 처분의 대상이 될 수 있습니다. 세부적인 법적 해석과 조치는 관할 기관 혹은 전문가를 통해 확인하시기 바랍니다.",
    "2-2": "관련 법령은 주기적으로 개정될 수 있습니다. 최신 개정 사항을 지속적으로 확인하여 법적 준수 상태를 유지하시기 바랍니다.",
    "2-3": "판단 확정을 위해서는 설비 적용 범위, 운전 조건, 예외 충족 여부 등 추가 정보 확인이 필요합니다.",
}

DESIGN_FIXED_INTROS = {
    "3-1": "검색된 문서를 기준으로 검토한 결과, 기술 지침상의 표준과 차이가 있는 설계 요소가 확인되었습니다.",
    "3-2": "검색된 문서를 기준으로 검토한 결과, 기술 지침상의 표준과 차이가 있는 설계 요소가 확인되지 않았습니다.",
    "3-3": "검색된 문서를 기준으로 검토한 결과, 현재 정보만으로는 설계오류 여부를 명확히 판단하기 어렵습니다.",
}

DESIGN_FIXED_OUTROS = {
    "3-1": "관련 지침 원문을 기준으로 해당 설계 요소를 재검토하고, 필요 시 사양, 배치, 보호장치 구성을 보완하시기 바랍니다.",
    "3-2": "현재 설계 조건을 유지하되, 설비 변경이나 운전 조건 변경 시에는 기술 지침 기준으로 재검토하시기 바랍니다.",
    "3-3": " ",
}

RESULT_SECTION_TITLES = {
    "risk": "## 공정위험성 검토 결과",
    "law": "## 법규위반 검토 결과",
    "design": "## 설계오류 검토 결과",
}

CASE_LABELS = {
    "1-1": "(1-1) 물질 매칭 YES + 설비 매칭 YES",
    "1-2": "(1-2) 물질 매칭 YES + 설비 매칭 NO",
    "1-3": "(1-3) 물질 매칭 NO + 설비 매칭 YES",
    "1-4": "(1-4) 물질 매칭 NO + 설비 매칭 NO + 물질 정보 YES",
    "1-5": "(1-5) 물질 매칭 NO + 설비 매칭 NO + 물질 정보 NO",
    "2-1": "(2-1) 법규위반 YES",
    "2-2": "(2-2) 법규위반 NO",
    "2-3": "(2-3) 법규위반 판단 불가",
    "2-4": "(2-4) 법규위반 근거 문서 없음",
    "3-1": "(3-1) 설계오류 YES",
    "3-2": "(3-2) 설계오류 NO",
    "3-3": "(3-3) 설계오류 판단 불가",
    "3-4": "(3-4) 설계오류 근거 문서 없음",
    "4-1": "(4-1) P&ID 관련 질문 아님",
}

LAW_DESIGN_CONTEXT_MAX_CHARS = 10000


def _truncate_context(text: str, max_chars: int) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _doc_label(doc: dict) -> str:
    return (
        doc.get("title")
        or doc.get("source")
        or doc.get("doc_id")
        or doc.get("id")
        or "제목 없음"
    )


def _score_doc_label(section_title: str, doc: dict) -> str:
    label = ""
    if section_title == "사고사례":
        label = str(
            doc.get("source")
            or doc.get("title")
            or doc.get("doc_id")
            or doc.get("id")
            or "제목 없음"
        )
    elif section_title == "화학물질정보":
        label = str(
            doc.get("source")
            or doc.get("title")
            or doc.get("chemical_name")
            or doc.get("doc_id")
            or doc.get("id")
            or "제목 없음"
        )
    else:
        label = str(_doc_label(doc))

    page = doc.get("page")
    if page not in (None, "") and "#page=" not in label:
        return f"{label} | #page={page}"
    return label


def _format_doc_scores(doc: dict) -> str:
    parts = []

    primary_score = doc.get("primary_score")
    if isinstance(primary_score, (int, float)):
        parts.append(f"1차={float(primary_score):.4f}")

    rerank_score = doc.get("rerank_score")
    if isinstance(rerank_score, (int, float)):
        parts.append(f"2차={float(rerank_score):.4f}")

    score = doc.get("score")
    if not parts and isinstance(score, (int, float)):
        parts.append(f"score={float(score):.4f}")

    return " | ".join(parts) if parts else "score=None"


def _format_score_lines(section_title: str, docs: list) -> str:
    if not has_usable_docs(docs):
        return ""

    lines = [f"### {section_title}"]
    for idx, doc in enumerate(docs, 1):
        if not isinstance(doc, dict):
            continue
        score_text = _format_doc_scores(doc)
        lines.append(f"- {idx}. {_score_doc_label(section_title, doc)} | {score_text}")
    return "\n".join(lines)


def _build_score_summary(sections: List[str]) -> str:
    sections = [section for section in sections if section]
    if not sections:
        return ""
    return "## 근거 문서 점수\n" + "\n\n".join(sections)


def _build_case_score_summary(case_code: str, score_summary: str) -> str:
    """분류 코드와 근거 문서 점수 블록을 결합합니다."""
    case_label = CASE_LABELS.get(str(case_code or "").strip(), "").strip()
    score_summary = (score_summary or "").strip()
    if case_label and score_summary:
        return f"[ 분류 코드: {case_label} ]\n{score_summary}"
    if case_label:
        return f"[ 분류 코드: {case_label} ]"
    return score_summary


def _risk_docs_to_context(docs: list, start_index: int = 1) -> str:
    lines = []
    cite_no = max(1, int(start_index)) - 1
    for doc in docs:
        if isinstance(doc, dict):
            text = str(doc.get("text") or doc.get("chunk_text") or "").strip()
            title = str(
                doc.get("title")
                or doc.get("source")
                or doc.get("doc_id")
                or doc.get("id")
                or "제목 없음"
            ).strip()
        else:
            text = str(doc).strip()
            title = "제목 없음"
        if not text:
            continue
        cite_no += 1
        lines.append(f"[CITE_{cite_no}]\n문서 제목: {title}\n본문:\n{text}")
    return "\n\n".join(lines)


def _extract_tagged_section(text: str, tag: str) -> str:
    if not text:
        return ""
    pattern = rf"\[{re.escape(tag)}\]\s*(.*?)(?=\n\[[^\]]+\]|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return ""
    value = match.group(1).strip()
    value = re.sub(r"\s*\n\s*", " ", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip()


def _risk_accident_docs_to_context(docs: list, start_index: int = 1) -> str:
    lines = []
    cite_no = max(1, int(start_index)) - 1
    case_no = 0
    for doc in docs:
        if isinstance(doc, dict):
            text = str(doc.get("text") or doc.get("chunk_text") or "").strip()
            title = str(
                doc.get("title")
                or doc.get("source")
                or doc.get("doc_id")
                or doc.get("id")
                or "제목 없음"
            ).strip()
        else:
            text = str(doc).strip()
            title = "제목 없음"
        if not text:
            continue

        cite_no += 1
        case_no += 1
        accident_content = _extract_tagged_section(text, "사고내용")
        equipment = _extract_tagged_section(text, "관련설비")
        material = _extract_tagged_section(text, "관련물질")
        accident_type = _extract_tagged_section(text, "사고유형")
        accident_cause = _extract_tagged_section(text, "사고원인")

        doc_lines = [f"[CITE_{cite_no}]"]
        doc_lines.append(f"문서 제목: {title}")
        doc_lines.append(f"[주요사례 번호] {case_no}")

        if accident_content:
            doc_lines.append(f"[사고내용] {accident_content}")
        if equipment:
            doc_lines.append(f"[관련설비] {equipment}")
        if material:
            doc_lines.append(f"[관련물질] {material}")
        if accident_type:
            doc_lines.append(f"[사고유형] {accident_type}")
        if accident_cause:
            doc_lines.append(f"[사고원인] {accident_cause}")

        if len(doc_lines) == 2:
            doc_lines.append(f"[본문] {text}")

        lines.append("\n".join(doc_lines))

    return "\n\n".join(lines)


def _count_usable_risk_docs(docs: list) -> int:
    count = 0
    for doc in docs:
        if isinstance(doc, dict):
            text = str(doc.get("text") or doc.get("chunk_text") or "").strip()
        else:
            text = str(doc).strip()
        if text:
            count += 1
    return count


def _select_risk_case(material_match: bool, equipment_match: bool) -> str:
    if material_match and equipment_match:
        return "(1-1) 물질 매칭 YES + 설비 매칭 YES"
    if material_match and not equipment_match:
        return "(1-2) 물질 매칭 YES + 설비 매칭 NO"
    if not material_match and equipment_match:
        return "(1-3) 물질 매칭 NO + 설비 매칭 YES"
    return "(1-4) 물질 매칭 NO + 설비 매칭 NO + 물질 정보 YES"


def _build_risk_fixed_intro(case_code: str, selected_accident_count: int, chemical_found: bool) -> str:
    if case_code == "1-1":
        return (
            f"동일 물질 및 유사 설비 사고 이력이 총 {selected_accident_count}건 발견되었습니다. "
            "유사 사고 사례가 확인되어 해당 케이스는 위험성이 높습니다."
        )
    if case_code == "1-2":
        return (
            f"동일 물질 사고 이력이 총 {selected_accident_count}건 발견되었습니다. "
            "설비 유형과 무관하게 해당 케이스는 위험할 수 있습니다."
        )
    if case_code == "1-3":
        return (
            f"유사 설비 사고 이력이 총 {selected_accident_count}건 발견되었습니다. "
            "취급 물질의 위험성이 낮더라도 기계적 위험성이 상존하여 해당 케이스는 위험할 수 있습니다."
        )
    if chemical_found:
        return "데이터베이스 내에 동일한 물질과 유사한 설비의 조합으로 매칭되는 사고 이력이 없습니다."
    return NO_EVIDENCE_RISK


def _prepend_fixed_intro(fixed_intro: str, body: str) -> str:
    body = (body or "").strip()
    fixed_intro = (fixed_intro or "").strip()
    if body.startswith(fixed_intro):
        body = body[len(fixed_intro):].lstrip()
    if not body:
        return fixed_intro
    return f"{fixed_intro}\n\n{body}"


def _prepend_inline_intro(inline_intro: str, body: str) -> str:
    body = (body or "").strip()
    inline_intro = (inline_intro or "").strip()
    if body.startswith(inline_intro):
        body = body[len(inline_intro):].lstrip()
    if not inline_intro:
        return body
    if not body:
        return inline_intro
    return f"{inline_intro} {body}"


def _resolve_law_case_key(case_code: str) -> str:
    case_code = str(case_code or "").strip()
    if "2-1" in case_code:
        return "2-1"
    if "2-2" in case_code:
        return "2-2"
    if "2-3" in case_code:
        return "2-3"
    return "2-3"


def _resolve_design_case_key(case_code: str) -> str:
    case_code = str(case_code or "").strip()
    if "3-1" in case_code:
        return "3-1"
    if "3-2" in case_code:
        return "3-2"
    if "3-3" in case_code:
        return "3-3"
    return "3-3"


def _compose_fixed_block_answer(fixed_intro: str, body: str, fixed_outro: str) -> str:
    parts = []
    if fixed_intro.strip():
        parts.append(fixed_intro.strip())
    if body.strip():
        parts.append(body.strip())
    if fixed_outro.strip():
        parts.append(fixed_outro.strip())
    return "\n\n".join(parts)


def _prepend_result_title(intent: str, answer: str) -> str:
    title = RESULT_SECTION_TITLES.get(intent, "").strip()
    answer = (answer or "").strip()
    if not title:
        return answer
    if not answer:
        return title
    return f"{title}\n\n{answer}"


def _strip_fixed_intro_prefix(body: str, fixed_intro: str) -> str:
    body = (body or "").strip()
    fixed_intro = (fixed_intro or "").strip()
    if fixed_intro and body.startswith(fixed_intro):
        return body[len(fixed_intro):].lstrip()
    return body


def _normalize_citation_punctuation(text: str) -> str:
    """- citation 표기의 공백·하이픈·문장부호 위치를 정규화합니다."""
    value = str(text or "")
    value = re.sub(r"\[\s*CITE_(\d+)\s*\]", r"[CITE_\1]", value)
    value = re.sub(r"(?<=[^\s])\s*-\s*(\[CITE_\d+\])", r" \1", value)
    value = re.sub(r"(\[CITE_\d+\])\s*([.!?。])", r"\2 \1", value)
    value = re.sub(r"\s+([.!?。])\s*(\[CITE_\d+\])", r"\1 \2", value)
    value = re.sub(r"([.!?。])[ \t]*(\[CITE_\d+\])", r"\1 \2", value)

    normalized_lines = []
    for line in value.splitlines():
        if re.match(r"^\s*주요사례\s+\d+\.", line):
            normalized_lines.append(line)
            continue
        line = re.sub(
            r"([^\s.!?。])\s*(\[CITE_\d+\])(?=(?:$|[ \t]+[가-힣A-Za-z0-9]))",
            r"\1. \2",
            line,
        )
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def generator_node(state: AgentState):
    """
    [노드: 답변 생성]
    검색된 문서를 카테고리별 최종 프롬프트에 직접 전달하여
    단일 의도에 대한 단일 보고서를 생성합니다.
    - risk만  → 사고사례/화학물질 검색 문서를 함께 전달
    - law만   → 법령 검색 문서를 직접 전달
    - design만→ 설계 가이드 검색 문서를 직접 전달
    - 2개 이상 의도→ 사용자에게 질문을 한 가지로 좁혀 달라는 안내(MULTI_INTENT_RESPONSE) 반환
    """
    intents = state.get("target_intents") or []
    intents = [i for i in intents if i in ("risk", "law", "design")]

    if not intents:
        return {"final_answer": ERROR_RESPONSE.strip()}

    if len(intents) > 1:
        return {"final_answer": MULTI_INTENT_RESPONSE.strip()}

    facility_info = state.get("facility_info", "")
    meta = state.get("search_metadata") or {}
    question = (state.get("question") or "").strip()
    selected_accident_count = meta.get("selected_accident_count", meta.get("risk_count", 0))
    chemical_found = meta.get("chemical_found", False)
    selected_risk_case_code = meta.get("selected_risk_case_code", "1-5")
    accident_docs = state.get("accident_docs") or []
    chemical_docs = state.get("chemical_docs") or []
    law_docs = state.get("law_docs") or []
    design_docs = state.get("design_docs") or []

    def _build_risk_final():
        if not (has_usable_docs(accident_docs) or has_usable_docs(chemical_docs)):
            return NO_EVIDENCE_RISK, "", _build_case_score_summary("1-5", "")

        if selected_risk_case_code == "1-5":
            return NO_EVIDENCE_RISK, "", _build_case_score_summary("1-5", "")

        inline_intro = ""
        if selected_risk_case_code == "1-4":
            inline_intro = "하지만 해당 물질의 일반적인 위험성을 간과해서는 안 됩니다."

        fixed_intro = _build_risk_fixed_intro(
            case_code=selected_risk_case_code,
            selected_accident_count=selected_accident_count,
            chemical_found=chemical_found or bool(chemical_docs),
        )
        accident_docs_context = _risk_accident_docs_to_context(accident_docs, start_index=1)
        accident_cite_count = _count_usable_risk_docs(accident_docs)
        chemical_docs_context = _risk_docs_to_context(
            chemical_docs,
            start_index=accident_cite_count + 1,
        )

        score_summary = _build_score_summary([
            _format_score_lines("사고사례", accident_docs),
            _format_score_lines("화학물질정보", chemical_docs),
        ])
        score_summary = _build_case_score_summary(selected_risk_case_code, score_summary)

        if selected_risk_case_code == "1-4":
            system_prompt, user_template = get_risk_final_prompt(selected_risk_case_code)
            user_content = user_template.format(
                question=question,
                facility_info=facility_info,
                accident_docs_context=accident_docs_context,
                chemical_docs_context=chemical_docs_context,
            )
            res = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ])
            body = (res.content or "").strip()
            body = _strip_fixed_intro_prefix(body, fixed_intro)
            body = _normalize_citation_punctuation(body)
            llm_body = body
            body = _prepend_inline_intro(inline_intro, body)
            answer = _prepend_fixed_intro(fixed_intro, body)
            return answer, llm_body, score_summary

        # 1-1, 1-2, 1-3: 설명/제안과 주요사례를 병렬 호출
        explain_sys, explain_user_tpl = get_risk_explain_prompt(selected_risk_case_code)
        cases_sys, cases_user_tpl = get_risk_cases_prompt()

        explain_user = explain_user_tpl.format(
            question=question,
            facility_info=facility_info,
            accident_docs_context=accident_docs_context,
            chemical_docs_context=chemical_docs_context,
        )
        cases_user = cases_user_tpl.format(
            question=question,
            accident_docs_context=accident_docs_context,
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_explain = pool.submit(
                llm.invoke,
                [SystemMessage(content=explain_sys), HumanMessage(content=explain_user)],
            )
            fut_cases = pool.submit(
                llm.invoke,
                [SystemMessage(content=cases_sys), HumanMessage(content=cases_user)],
            )
            explain_body = (fut_explain.result().content or "").strip()
            cases_body = (fut_cases.result().content or "").strip()

        explain_body = _strip_fixed_intro_prefix(explain_body, fixed_intro)
        explain_body = _normalize_citation_punctuation(explain_body)
        cases_body = _normalize_citation_punctuation(cases_body)
        body = f"{explain_body}\n\n{cases_body}" if cases_body else explain_body
        llm_body = body
        answer = _prepend_fixed_intro(fixed_intro, body)
        return answer, llm_body, score_summary

    def _build_law_final():
        if not has_usable_docs(law_docs):
            return NO_EVIDENCE_LAW, "", _build_case_score_summary("2-4", "")
        law_docs_context = _truncate_context(
            scored_docs_to_context(law_docs),
            LAW_DESIGN_CONTEXT_MAX_CHARS,
        )
        case_messages = [
            SystemMessage(content=LAW_CASE_SELECTOR_SYSTEM_PROMPT),
            HumanMessage(content=LAW_CASE_SELECTOR_USER_TEMPLATE.format(
                facility_info=facility_info,
                law_docs_context=law_docs_context,
            )),
        ]
        case_res = llm.invoke(case_messages)
        selected_law_case = _resolve_law_case_key((case_res.content or "").strip())
        fixed_intro = LAW_FIXED_INTROS[selected_law_case]
        fixed_outro = LAW_FIXED_OUTROS[selected_law_case]
        system_prompt, user_template = get_law_final_prompt(selected_law_case)
        user_content = user_template.format(
            facility_info=facility_info,
            law_docs_context=law_docs_context,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]
        res = llm.invoke(messages)
        body = _normalize_citation_punctuation((res.content or "").strip())
        llm_body = body
        answer = _compose_fixed_block_answer(fixed_intro, body, fixed_outro)
        score_summary = _build_score_summary([
            _format_score_lines("법령·고시", law_docs),
        ])
        score_summary = _build_case_score_summary(selected_law_case, score_summary)
        return answer, llm_body, score_summary

    def _build_design_final():
        if not has_usable_docs(design_docs):
            return NO_EVIDENCE_DESIGN, "", _build_case_score_summary("3-4", "")
        design_docs_context = _truncate_context(
            scored_docs_to_context(design_docs),
            LAW_DESIGN_CONTEXT_MAX_CHARS,
        )
        case_messages = [
            SystemMessage(content=DESIGN_CASE_SELECTOR_SYSTEM_PROMPT),
            HumanMessage(content=DESIGN_CASE_SELECTOR_USER_TEMPLATE.format(
                facility_info=facility_info,
                design_docs_context=design_docs_context,
            )),
        ]
        case_res = llm.invoke(case_messages)
        selected_design_case = _resolve_design_case_key((case_res.content or "").strip())
        fixed_intro = DESIGN_FIXED_INTROS[selected_design_case]
        fixed_outro = DESIGN_FIXED_OUTROS[selected_design_case]
        system_prompt, user_template = get_design_final_prompt(selected_design_case)
        user_content = user_template.format(
            facility_info=facility_info,
            design_docs_context=design_docs_context,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]
        res = llm.invoke(messages)
        body = _normalize_citation_punctuation((res.content or "").strip())
        llm_body = body
        answer = _compose_fixed_block_answer(fixed_intro, body, fixed_outro)
        score_summary = _build_score_summary([
            _format_score_lines("설계지침·가이드", design_docs),
        ])
        score_summary = _build_case_score_summary(selected_design_case, score_summary)
        return answer, llm_body, score_summary

    if intents == ["risk"]:
        answer, llm_body, score_summary = _build_risk_final()
        final_answer = _prepend_result_title("risk", answer)
        return {"final_answer": final_answer, "llm_body": llm_body, "score_summary": score_summary}
    if intents == ["law"]:
        answer, llm_body, score_summary = _build_law_final()
        final_answer = _prepend_result_title("law", answer)
        return {"final_answer": final_answer, "llm_body": llm_body, "score_summary": score_summary}
    if intents == ["design"]:
        answer, llm_body, score_summary = _build_design_final()
        final_answer = _prepend_result_title("design", answer)
        return {"final_answer": final_answer, "llm_body": llm_body, "score_summary": score_summary}
    return {"final_answer": ERROR_RESPONSE.strip(), "llm_body": "", "score_summary": ""}
