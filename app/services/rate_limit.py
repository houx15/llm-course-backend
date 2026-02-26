from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.core.security import now_utc
from app.models import AuthRateLimitEvent

settings = get_settings()


def _count_events(db: Session, action: str, identifier: str, since):
    stmt = select(func.count()).select_from(AuthRateLimitEvent).where(
        AuthRateLimitEvent.action == action,
        AuthRateLimitEvent.identifier == identifier,
        AuthRateLimitEvent.created_at >= since,
    )
    return int(db.execute(stmt).scalar_one())


def _latest_event(db: Session, action: str, identifier: str):
    stmt = (
        select(AuthRateLimitEvent)
        .where(AuthRateLimitEvent.action == action, AuthRateLimitEvent.identifier == identifier)
        .order_by(AuthRateLimitEvent.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def check_and_record_waitlist_request(db: Session, email: str, client_ip: str) -> None:
    """Rate-limit waitlist submissions by IP and email."""
    now = now_utc()
    window_since = now - timedelta(seconds=settings.waitlist_window_seconds)

    ip_action = "waitlist_ip"
    email_action = "waitlist_email"

    ip_count = _count_events(db, ip_action, client_ip, window_since)
    if ip_count >= settings.waitlist_max_per_ip_window:
        raise ApiError(status_code=429, code=ErrorCode.TOO_MANY_REQUESTS, message="请求过于频繁，请稍后再试")

    email_count = _count_events(db, email_action, email, window_since)
    if email_count >= settings.waitlist_max_per_email_window:
        raise ApiError(status_code=429, code=ErrorCode.TOO_MANY_REQUESTS, message="该邮箱请求过于频繁，请稍后再试")

    latest = _latest_event(db, email_action, email)
    if latest:
        cooldown = (now - latest.created_at).total_seconds()
        if cooldown < settings.waitlist_cooldown_seconds:
            raise ApiError(status_code=429, code=ErrorCode.TOO_MANY_REQUESTS, message="请稍等片刻后再试")

    db.add(AuthRateLimitEvent(action=ip_action, identifier=client_ip, created_at=now))
    db.add(AuthRateLimitEvent(action=email_action, identifier=email, created_at=now))


def check_and_record_email_code_request(db: Session, email: str, client_ip: str) -> None:
    now = now_utc()
    window_since = now - timedelta(seconds=settings.auth_code_window_seconds)

    email_action = "email_code_email"
    ip_action = "email_code_ip"

    email_count = _count_events(db, email_action, email, window_since)
    if email_count >= settings.auth_code_max_per_email_window:
        raise ApiError(status_code=429, code=ErrorCode.TOO_MANY_REQUESTS, message="Too many requests for this email")

    ip_count = _count_events(db, ip_action, client_ip, window_since)
    if ip_count >= settings.auth_code_max_per_ip_window:
        raise ApiError(status_code=429, code=ErrorCode.TOO_MANY_REQUESTS, message="Too many requests from this IP")

    latest = _latest_event(db, email_action, email)
    if latest:
        cooldown = (now - latest.created_at).total_seconds()
        if cooldown < settings.auth_code_cooldown_seconds:
            raise ApiError(status_code=429, code=ErrorCode.TOO_MANY_REQUESTS, message="Please wait before requesting another code")

    db.add(AuthRateLimitEvent(action=email_action, identifier=email, created_at=now))
    db.add(AuthRateLimitEvent(action=ip_action, identifier=client_ip, created_at=now))
