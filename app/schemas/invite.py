from datetime import datetime

from pydantic import BaseModel, Field


class GenerateInviteCodesRequest(BaseModel):
    count: int = Field(ge=1, le=10000, default=100)


class InviteCodeItem(BaseModel):
    code: str
    created_at: datetime
    used: bool
    used_by_email: str | None = None
    used_at: datetime | None = None


class GenerateInviteCodesResponse(BaseModel):
    codes: list[str]
    count: int


class InviteCodeListResponse(BaseModel):
    codes: list[InviteCodeItem]
    total: int
    used_count: int


class UserInviteCodeResponse(BaseModel):
    code: str
