from langchain_core.messages import SystemMessage, HumanMessage

from src.core.state import AgentState
from src.core.nodes.utils import llm, scored_docs_to_context, has_usable_docs, format_node_output
from src.prompts.check_designs import (
    DESIGN_SYSTEM_PROMPT,
    DESIGN_USER_TEMPLATE,
    NO_EVIDENCE_DESIGN,
)


def design_analysis_node(state: AgentState):
    """
    [노드: 설계 가이드 분석]
    라우터에서 'design' 의도가 감지되었을 때 실행됩니다.
    기술 지침(KOSHA Guide 등)을 기반으로 설계 적정성을 검토합니다.
    """
    intents = state.get("target_intents") or []
    if "design" not in intents:
        return {}

    print(">>>>> [NODE] Design Node <<<<<")
    docs = state.get("design_docs") or []
    existing = list(state.get("partial_answers") or [])

    if not has_usable_docs(docs):
        msg = NO_EVIDENCE_DESIGN.strip()
        return {
            "partial_answers": existing + [msg],
            "node_outputs": {"design": msg},
        }

    messages = [
        SystemMessage(content=DESIGN_SYSTEM_PROMPT),
        HumanMessage(
            content=DESIGN_USER_TEMPLATE.format(
                facility_info=state.get("facility_info", ""),
                context=scored_docs_to_context(docs),
            )
        ),
    ]
    res = llm.invoke(messages)

    content = format_node_output((res.content or "").strip(), docs)
    return {
        "partial_answers": existing + [content],
        "node_outputs": {"design": content},
    }
