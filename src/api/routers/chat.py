from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Body, HTTPException
from src.api.schemas import ChatRequest, ChatResponse, SourceItem
KST = timezone(timedelta(hours=9))


router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest = Body(
        ...,
        examples=[
            {
                "thread_id": "string",
                "user_message": "string",
                "file_id": "string",
                "equip_id": "string",
                "facility_info": {},
            }
        ],
    )
) -> ChatResponse:
    try:
        from src.services import chat_service
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"chat_service import failed: {exc}",
        ) from exc

    if not hasattr(chat_service, "chat"):
        raise HTTPException(
            status_code=503,
            detail="chat_service.chat is not ready.",
        )

    result = await chat_service.chat(
        thread_id=req.thread_id,
        user_message=req.user_message,
        facility_info=req.facility_info,
    )

    return ChatResponse(
        file_id=req.file_id,
        equip_id=req.equip_id,
        thread_id=req.thread_id,
        status="success",
        created_at=datetime.now(KST).replace(microsecond=0).isoformat(),
        answer=result["answer"],
        sources=[SourceItem(**item) for item in result.get("sources", [])],
    )
