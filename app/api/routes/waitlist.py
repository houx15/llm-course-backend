"""Public waitlist endpoint — no authentication required."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette import status

from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import WaitlistEntry
from app.schemas.waitlist import WaitlistRequest, WaitlistResponse
from app.services.email_sender import send_waitlist_confirmation

router = APIRouter(prefix="/v1", tags=["waitlist"])


@router.post("/waitlist", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
def join_waitlist(
    payload: WaitlistRequest,
    db: Session = Depends(get_db),
) -> WaitlistResponse:
    email = payload.email.lower().strip()

    existing = db.execute(
        select(WaitlistEntry).where(WaitlistEntry.email == email)
    ).scalars().first()
    if existing:
        return WaitlistResponse(email=email, message="您已在等待列表中")

    entry = WaitlistEntry(email=email)
    db.add(entry)
    db.commit()

    try:
        send_waitlist_confirmation(email)
    except Exception:
        pass  # Best-effort: don't fail the request if email fails

    return WaitlistResponse(email=email, message="已加入等待列表，我们会通过邮件通知您")
