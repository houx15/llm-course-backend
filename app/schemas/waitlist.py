from datetime import datetime

from pydantic import BaseModel, EmailStr


class WaitlistRequest(BaseModel):
    email: EmailStr


class WaitlistResponse(BaseModel):
    email: str
    message: str
