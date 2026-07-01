from langchain_core.messages import SystemMessage, HumanMessage

from src.core.state import AgentState
from src.core.nodes.utils import llm, scored_docs_to_context, has_usable_docs, format_node_output


NO_EVIDENCE_CHEMICAL = """
검색된 화학물질 정보가 없습니다.
"""


CHEMICAL_SYSTEM_PROMPT = """
당신은 검색된 화학물질 정보 정리자입니다.
- 검색 문서 밖의 내용은 쓰지 마십시오.
- 조건과 수치는 바꾸거나 일반화하지 마십시오.
- 화학물질 성질과 위험 정보만 정리하십시오. 대책, 권고, 최종 판단은 금지합니다.
- 표, 문서 ID, 페이지, 점수, 참고 문구는 금지합니다.
- 문서가 비면 "검색된 화학물질 정보가 없습니다"만 출력하십시오.
"""


CHEMICAL_USER_TEMPLATE = """
[설비 및 취급 정보]
{facility_info}

[검색된 화학물질 정보]
{context}
"""


def chemical_analysis_node(state: AgentState):
    """
    [노드: 화학 물질 분석]
    Chemicals 테이블(하이브리드 검색)에서 가져온 물질의 유해성, 반응성, 독성 정보를 분석합니다.
    """
    intents = state.get("target_intents") or []
    if "risk" not in intents:
        return {}

    print(">>>>> [NODE] Chemical Node <<<<<")
    docs = state.get("chemical_docs") or []
    existing = list(state.get("partial_answers") or [])

    if not has_usable_docs(docs):
        msg = NO_EVIDENCE_CHEMICAL.strip()
        return {
            "partial_answers": existing + [msg],
            "node_outputs": {"chemical": msg},
        }

    messages = [
        SystemMessage(content=CHEMICAL_SYSTEM_PROMPT),
        HumanMessage(
            content=CHEMICAL_USER_TEMPLATE.format(
                facility_info=state.get("facility_info", ""),
                context=scored_docs_to_context(docs),
            )
        ),
    ]
    res = llm.invoke(messages)

    content = format_node_output((res.content or "").strip(), docs)
    return {
        "partial_answers": existing + [content],
        "node_outputs": {"chemical": content},
    }
