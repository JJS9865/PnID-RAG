from src.core.state import AgentState
from src.prompts.fallback import ERROR_RESPONSE

FALLBACK_CASE_SUMMARY = "[ 분류 코드: (4-1) P&ID 관련 질문 아님 ]"


def fallback_node(state: AgentState):
    """
    [노드: Fallback]
    사용자의 질문이 정해진 3가지 카테고리(위험/법규/설계)에 속하지 않을 경우,
    안내 메시지를 반환하여 사용자가 올바른 질문을 하도록 유도합니다.
    """
    return {
        "final_answer": ERROR_RESPONSE.strip(),
        "score_summary": FALLBACK_CASE_SUMMARY,
    }
