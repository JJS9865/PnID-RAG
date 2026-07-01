from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, description="사용자 ID")
    user_message: str = Field(..., min_length=1, description="사용자 질문")
    file_id: Optional[str] = Field(default=None, description="도면 ID")
    equip_id: Optional[str] = Field(default=None, description="설비 ID")
    facility_info: Dict[str, Any] = Field(
        default_factory=dict,
        description="P&ID JSON 정보",
        examples=[{}],
    )


class SourceItem(BaseModel):
    doc_id: Optional[str] = None
    title: Optional[str] = None
    page: Optional[int] = None
    chunk_text: Optional[str] = None
    score: Optional[float] = None
    pdf_url: Optional[str] = None


class ChatResponse(BaseModel):
    file_id: Optional[str] = None
    equip_id: Optional[str] = None
    thread_id: str
    status: str = "success"
    created_at: str
    answer: str
    sources: List[SourceItem] = Field(default_factory=list)
