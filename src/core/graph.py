from langgraph.graph import StateGraph, END
from src.core.state import AgentState
from src.services.search_engine import SearchEngine
from src.prompts.fallback import MULTI_INTENT_RESPONSE
from src.core.nodes import (
    rewriter_node,
    router_node,
    generator_node,
    fallback_node,
)


def start_node(state: AgentState):
    """그래프 실행을 시작하기 위한 진입 노드"""
    return {}


def _has_any_intent(intents: list) -> bool:
    """사용자 의도에 분석 가능한 카테고리(risk, law, design)가 있는지 확인"""
    if not intents:
        return False
    targets = ["risk", "law", "design"]
    for t in targets:
        if t in intents:
            return True
    return False


def route_after_router(state: AgentState):
    """Router 실행 후 분기: 다중의도 / 재작성 / 종료"""
    intents = state.get("target_intents") or []
    if len(intents) > 1:
        # 의도가 2개 이상이면 검색 없이 바로 한 가지만 선택해 달라고 응답
        return "multi_intent_clarify"
    if _has_any_intent(intents):
        return "rewriter"
    return "fallback"


def multi_intent_clarify_node(state: AgentState):
    """의도가 2개 이상일 때 검색 없이 사용자에게 한 가지 주제만 선택해 달라고 안내"""
    return {"final_answer": MULTI_INTENT_RESPONSE.strip()}


def retrieve_node(state: AgentState):
    """[노드] 검색 엔진 실행"""
    print(">>>>> [NODE] Retriever <<<<<")
    engine = SearchEngine()
    
    query = state.get("search_query") or state.get("question") or ""
    intents = state.get("target_intents") or []
    filters = {
        "material": state.get("target_material"),
        "equipment": state.get("target_equipment"),
    }
    
    return engine.search(query, intents, filters)


# Graph 정의
workflow = StateGraph(AgentState)

# 1. 노드 등록
workflow.add_node("start", start_node)
workflow.add_node("router", router_node)
workflow.add_node("rewriter", rewriter_node)
workflow.add_node("fallback", fallback_node)
workflow.add_node("multi_intent_clarify", multi_intent_clarify_node)
workflow.add_node("retriever", retrieve_node)
workflow.add_node("generator", generator_node)

# 2. 엣지 연결
workflow.set_entry_point("start")
workflow.add_edge("start", "router")

# Router -> 다중의도(질문 재요청) / Rewriter / Fallback
workflow.add_conditional_edges("router", route_after_router, 
    {
        "multi_intent_clarify": "multi_intent_clarify",
        "rewriter": "rewriter",
        "fallback": "fallback",
    }
)
workflow.add_edge("fallback", END)
workflow.add_edge("multi_intent_clarify", END)
workflow.add_edge("rewriter", "retriever")
workflow.add_edge("retriever", "generator")
workflow.add_edge("generator", END)

# 3. 컴파일
app_graph = workflow.compile()