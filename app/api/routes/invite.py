"""Invite code endpoints: admin batch generation, user self-generation, admin listing."""

import random
import string

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette import status

from app.api.admin_auth import require_admin_key
from app.api.deps import CurrentUser
from app.db.session import get_db
from app.models import InviteCode, User
from app.schemas.invite import (
    GenerateInviteCodesRequest,
    GenerateInviteCodesResponse,
    InviteCodeItem,
    InviteCodeListResponse,
    UserInviteCodeResponse,
)

router = APIRouter(prefix="/v1", tags=["invite"])


def _generate_code() -> str:
    """Generate a short uppercase alphanumeric invite code."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=8))


def _generate_unique_codes(db: Session, count: int, created_by: str | None = None) -> list[str]:
    """Generate `count` unique invite codes and insert them."""
    codes: list[str] = []
    attempts = 0
    while len(codes) < count and attempts < count * 3:
        attempts += 1
        code = _generate_code()
        exists = db.execute(select(InviteCode.id).where(InviteCode.code == code)).scalar_one_or_none()
        if exists:
            continue
        row = InviteCode(code=code, created_by_user_id=created_by)
        db.add(row)
        codes.append(code)
    db.commit()
    return codes


# ── Admin endpoints ─────────────────────────────────────────────────────────


@router.post(
    "/admin/invite-codes/generate",
    response_model=GenerateInviteCodesResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_key)],
)
def admin_generate_invite_codes(
    payload: GenerateInviteCodesRequest,
    db: Session = Depends(get_db),
) -> GenerateInviteCodesResponse:
    """Admin: batch-generate invite codes."""
    codes = _generate_unique_codes(db, payload.count)
    return GenerateInviteCodesResponse(codes=codes, count=len(codes))


@router.get(
    "/admin/invite-codes",
    response_model=InviteCodeListResponse,
    dependencies=[Depends(require_admin_key)],
)
def admin_list_invite_codes(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    unused_only: bool = Query(default=False),
) -> InviteCodeListResponse:
    """Admin: list invite codes with usage status."""
    base = select(InviteCode)
    if unused_only:
        base = base.where(InviteCode.used_at.is_(None))

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
    used_count = db.execute(
        select(func.count()).select_from(InviteCode).where(InviteCode.used_at.isnot(None))
    ).scalar() or 0

    rows = db.execute(
        base.outerjoin(User, InviteCode.used_by_user_id == User.id)
        .add_columns(User.email)
        .order_by(InviteCode.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    items = [
        InviteCodeItem(
            code=invite.code,
            created_at=invite.created_at,
            used=invite.used_at is not None,
            used_by_email=email,
            used_at=invite.used_at,
        )
        for invite, email in rows
    ]

    return InviteCodeListResponse(codes=items, total=total, used_count=used_count)


# ── User endpoint ───────────────────────────────────────────────────────────


@router.post(
    "/invite-codes/generate",
    response_model=UserInviteCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
def user_generate_invite_code(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> UserInviteCodeResponse:
    """Authenticated user: generate one invite code to share."""
    codes = _generate_unique_codes(db, 1, created_by=str(current_user.id))
    return UserInviteCodeResponse(code=codes[0])
