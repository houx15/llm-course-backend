from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.auth import UserOut

router = APIRouter(prefix="/v1", tags=["users"])


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser) -> UserOut:
    return UserOut(id=str(current_user.id), email=current_user.email, display_name=current_user.display_name)
