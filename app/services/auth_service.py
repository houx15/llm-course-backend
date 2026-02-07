from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.core.security import create_access_token, generate_refresh_token, hash_text, now_utc
from app.models import DeviceSession, EmailVerificationCode, User
from app.schemas.auth import AuthResponse, UserOut

settings = get_settings()


def consume_verification_code(db: Session, email: str, purpose: str, code: str) -> None:
    # Dev-only bypass for local testing without SMTP/domain.
    if settings.app_env != "production" and settings.dev_fixed_email_code and code == settings.dev_fixed_email_code:
        return

    stmt = (
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == purpose,
            EmailVerificationCode.used_at.is_(None),
        )
        .order_by(EmailVerificationCode.created_at.desc())
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise ApiError(400, ErrorCode.VERIFICATION_CODE_NOT_FOUND, "Verification code not found")

    if row.expires_at < now_utc():
        raise ApiError(400, ErrorCode.VERIFICATION_CODE_EXPIRED, "Verification code expired")

    if row.code_hash != hash_text(code):
        row.attempt_count += 1
        db.add(row)
        db.commit()
        raise ApiError(400, ErrorCode.INVALID_VERIFICATION_CODE, "Verification code is invalid")

    row.used_at = now_utc()
    db.add(row)
    db.commit()


def issue_session_tokens(db: Session, user: User, device_id: str) -> AuthResponse:
    refresh_token = generate_refresh_token()
    refresh_hash = hash_text(refresh_token)

    # Revoke prior active session for this user + device
    prior_stmt = select(DeviceSession).where(
        DeviceSession.user_id == user.id,
        DeviceSession.device_id == device_id,
        DeviceSession.revoked_at.is_(None),
    )
    prior = db.execute(prior_stmt).scalars().all()
    for item in prior:
        item.revoked_at = now_utc()
        db.add(item)

    session = DeviceSession(
        user_id=user.id,
        device_id=device_id,
        refresh_token_hash=refresh_hash,
        expires_at=now_utc() + timedelta(seconds=settings.refresh_token_expire_seconds),
        last_seen_at=now_utc(),
        revoked_at=None,
    )
    db.add(session)
    db.commit()

    access_token = create_access_token(str(user.id), extra={"email": user.email})

    return AuthResponse(
        user=UserOut(id=str(user.id), email=user.email, display_name=user.display_name),
        access_token=access_token,
        access_token_expires_in=settings.access_token_expire_seconds,
        refresh_token=refresh_token,
    )
