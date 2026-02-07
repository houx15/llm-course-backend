from datetime import timedelta

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.core.security import create_access_token, generate_email_code, hash_text, now_utc
from app.db.session import get_db
from app.models import DeviceSession, EmailVerificationCode, User
from app.schemas.auth import (
    AuthResponse,
    EmailCodeRequest,
    EmailCodeResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterOrLoginRequest,
)
from app.services.auth_service import consume_verification_code, issue_session_tokens
from app.services.email_sender import send_verification_code
from app.services.rate_limit import check_and_record_email_code_request

router = APIRouter(prefix="/v1/auth", tags=["auth"])
settings = get_settings()


def _extract_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@router.post("/request-email-code", response_model=EmailCodeResponse)
def request_email_code(payload: EmailCodeRequest, request: Request, db: Session = Depends(get_db)) -> EmailCodeResponse:
    email = payload.email.lower().strip()

    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if payload.purpose == "register" and user:
        raise ApiError(status_code=400, code=ErrorCode.EMAIL_ALREADY_REGISTERED, message="Email already registered")
    if payload.purpose == "login" and not user:
        raise ApiError(status_code=404, code=ErrorCode.USER_NOT_FOUND, message="User not found")

    check_and_record_email_code_request(db, email=email, client_ip=_extract_client_ip(request))

    # Soft-expire previous unconsumed code of same purpose.
    active_codes = db.execute(
        select(EmailVerificationCode).where(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == payload.purpose,
            EmailVerificationCode.used_at.is_(None),
        )
    ).scalars().all()
    for item in active_codes:
        item.used_at = now_utc()
        db.add(item)

    plain_code = generate_email_code()
    if settings.app_env != "production" and settings.dev_fixed_email_code:
        plain_code = settings.dev_fixed_email_code
    code_row = EmailVerificationCode(
        email=email,
        purpose=payload.purpose,
        code_hash=hash_text(plain_code),
        expires_at=now_utc() + timedelta(seconds=settings.email_code_expire_seconds),
        attempt_count=0,
    )
    db.add(code_row)

    try:
        send_verification_code(email=email, code=plain_code, purpose=payload.purpose)
    except ValueError as exc:
        db.rollback()
        raise ApiError(status_code=500, code=ErrorCode.SERVER_MISCONFIGURED, message=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise ApiError(status_code=502, code=ErrorCode.EMAIL_SEND_FAILED, message="Failed to send verification code") from exc

    db.commit()

    dev_code = plain_code if settings.app_env != "production" else None
    return EmailCodeResponse(sent=True, expires_in_seconds=settings.email_code_expire_seconds, dev_code=dev_code)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterOrLoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = payload.email.lower().strip()

    exists = db.execute(select(User).where(User.email == email)).scalars().first()
    if exists:
        raise ApiError(status_code=400, code=ErrorCode.EMAIL_ALREADY_REGISTERED, message="Email already registered")

    consume_verification_code(db, email=email, purpose="register", code=payload.verification_code)

    display_name = payload.display_name or email.split("@")[0]
    user = User(email=email, display_name=display_name, status="active")
    db.add(user)
    db.commit()
    db.refresh(user)

    return issue_session_tokens(db, user=user, device_id=payload.device_id)


@router.post("/login", response_model=AuthResponse)
def login(payload: RegisterOrLoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = payload.email.lower().strip()
    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if not user:
        raise ApiError(status_code=404, code=ErrorCode.USER_NOT_FOUND, message="User not found")

    consume_verification_code(db, email=email, purpose="login", code=payload.verification_code)
    return issue_session_tokens(db, user=user, device_id=payload.device_id)


@router.post("/refresh", response_model=RefreshResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> RefreshResponse:
    token_hash = hash_text(payload.refresh_token)
    row = db.execute(select(DeviceSession).where(DeviceSession.refresh_token_hash == token_hash)).scalars().first()
    if not row or row.revoked_at is not None:
        raise ApiError(status_code=401, code=ErrorCode.INVALID_REFRESH_TOKEN, message="Invalid refresh token")
    if row.device_id != payload.device_id:
        raise ApiError(status_code=401, code=ErrorCode.DEVICE_MISMATCH, message="Device mismatch")
    if row.expires_at < now_utc():
        raise ApiError(status_code=401, code=ErrorCode.REFRESH_TOKEN_EXPIRED, message="Refresh token expired")

    user = db.get(User, row.user_id)
    if not user:
        raise ApiError(status_code=401, code=ErrorCode.INVALID_USER, message="Invalid user")

    row.last_seen_at = now_utc()
    db.add(row)
    db.commit()

    access_token = create_access_token(str(user.id), extra={"email": user.email})
    return RefreshResponse(access_token=access_token, access_token_expires_in=settings.access_token_expire_seconds)


@router.post("/logout", response_model=LogoutResponse)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> LogoutResponse:
    token_hash = hash_text(payload.refresh_token)
    row = db.execute(select(DeviceSession).where(DeviceSession.refresh_token_hash == token_hash)).scalars().first()
    if row and row.revoked_at is None:
        row.revoked_at = now_utc()
        db.add(row)
        db.commit()
    return LogoutResponse(success=True)
