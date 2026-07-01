from langchain_core.messages import SystemMessage, HumanMessage

from src.core.state import AgentState
from src.core.nodes.utils import llm, scored_docs_to_context, has_usable_docs, format_node_output
from src.prompts.check_laws import (
    LAW_SYSTEM_PROMPT,
    LAW_USER_TEMPLATE,
    NO_EVIDENCE_LAW,
)


def law_analysis_node(state: AgentState):
    """
    [노드: 법규 분석]
    라우터에서 'law' 의도가 감지되었을 때 실행됩니다.
    관련 법령/고시 문서(law_docs)를 기반으로 위반 여부를 검토합니다.
    """
    intents = state.get("target_intents") or []
    if "law" not in intents:
        return {}

    print(">>>>> [NODE] Law Node <<<<<")
    docs = state.get("law_docs") or []
    existing = list(state.get("partial_answers") or [])

    if not has_usable_docs(docs):
        msg = NO_EVIDENCE_LAW.strip()
        return {
            "partial_answers": existing + [msg],
            "node_outputs": {"law": msg},
        }

    messages = [
        SystemMessage(content=LAW_SYSTEM_PROMPT),
        HumanMessage(
            content=LAW_USER_TEMPLATE.format(
                facility_info=state.get("facility_info", ""),
                context=scored_docs_to_context(docs),
            )
        ),
    ]
    res = llm.invoke(messages)

    content = format_node_output((res.content or "").strip(), docs)
    return {
        "partial_answers": existing + [content],
        "node_outputs": {"law": content},
    }
