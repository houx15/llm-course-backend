from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.schemas.auth import UserOut
from app.schemas.users import ChangePasswordRequest, ChangePasswordResponse, UpdateProfileRequest

router = APIRouter(prefix="/v1", tags=["users"])


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser) -> UserOut:
    return UserOut(id=str(current_user.id), email=current_user.email, display_name=current_user.display_name)


@router.patch("/users/me/profile", response_model=UserOut)
def update_profile(
    payload: UpdateProfileRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> UserOut:
    current_user.display_name = payload.display_name
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return UserOut(id=str(current_user.id), email=current_user.email, display_name=current_user.display_name)


@router.post("/users/me/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ChangePasswordResponse:
    if not current_user.password_hash or not verify_password(payload.current_password, current_user.password_hash):
        raise ApiError(status_code=400, code=ErrorCode.WRONG_PASSWORD, message="当前密码不正确")

    current_user.password_hash = hash_password(payload.new_password)
    db.add(current_user)
    db.commit()
    return ChangePasswordResponse(changed=True)
