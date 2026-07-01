import operator
from typing import Annotated, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """
    LangGraph 상태 정의.
    - 4개 DB 테이블 구조 반영 (accidents, chemicals, laws, designs)
    - 병렬 실행 시 답변 유실 방지를 위한 reducer 적용
    """

    # 1. 입력 데이터
    question: str
    facility_info: str

    # 2. 처리 과정 데이터
    search_query: str
    target_intents: List[str]  # 예: ['risk', 'law', 'design'] 또는 ['general']
    target_material: Optional[str]
    target_equipment: Optional[str]

    # 3. 검색 결과 (DB 테이블 1:1 매핑)
    accident_docs: List[dict]
    chemical_docs: List[dict]
    law_docs: List[dict]
    design_docs: List[dict]
    search_metadata: dict

    # 4. 출력 데이터
    partial_answers: Annotated[List[str], operator.add]
    node_outputs: Annotated[Dict[str, str], operator.or_]  # 노드별 원문 출력(포맷 유지)
    final_answer: str
    llm_body: str
    score_summary: str