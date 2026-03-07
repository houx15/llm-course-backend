from pydantic import BaseModel, Field


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordResponse(BaseModel):
    changed: bool
