import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_text(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_email_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    expire_at = now_utc() + timedelta(seconds=settings.access_token_expire_seconds)
    payload: dict[str, Any] = {"sub": subject, "exp": expire_at, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
