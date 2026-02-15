from fastapi import Header

from app.core.config import get_settings
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError


def require_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    settings = get_settings()
    if not settings.admin_api_key:
        raise ApiError(status_code=403, code=ErrorCode.UNAUTHORIZED, message="Admin endpoints are disabled")
    if x_admin_key != settings.admin_api_key:
        raise ApiError(status_code=403, code=ErrorCode.UNAUTHORIZED, message="Invalid admin key")
