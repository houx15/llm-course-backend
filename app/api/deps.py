from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise ApiError(status_code=401, code=ErrorCode.UNAUTHORIZED, message="Missing authorization token")

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if payload.get("type") != "access" or not user_id:
            raise ApiError(status_code=401, code=ErrorCode.INVALID_TOKEN, message="Invalid token")
    except jwt.PyJWTError as exc:
        raise ApiError(status_code=401, code=ErrorCode.INVALID_TOKEN, message="Invalid or expired token") from exc

    user = db.get(User, user_id)
    if not user or user.status != "active":
        raise ApiError(status_code=401, code=ErrorCode.INVALID_USER, message="User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
