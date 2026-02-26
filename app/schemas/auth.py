from pydantic import BaseModel, EmailStr, Field


class EmailCodeRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(pattern="^(register)$")


class EmailCodeResponse(BaseModel):
    sent: bool
    expires_in_seconds: int
    dev_code: str | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    verification_code: str = Field(min_length=4, max_length=12)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    device_id: str = Field(min_length=1, max_length=255)
    invite_code: str = Field(min_length=4, max_length=32)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    device_id: str = Field(min_length=1, max_length=255)


class RefreshRequest(BaseModel):
    refresh_token: str
    device_id: str = Field(min_length=1, max_length=255)


class LogoutRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    display_name: str


class AuthResponse(BaseModel):
    user: UserOut
    access_token: str
    access_token_expires_in: int
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    access_token_expires_in: int


class LogoutResponse(BaseModel):
    success: bool
