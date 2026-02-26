from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BugReportUrlRequest(BaseModel):
    file_size_bytes: int = Field(gt=0)


class BugReportUrlResponse(BaseModel):
    bug_id: str
    presigned_url: str
    oss_key: str
    required_headers: dict[str, str] = {}


class BugReportConfirmRequest(BaseModel):
    bug_id: str
    oss_key: str
    file_size_bytes: int = Field(gt=0)
    app_version: str = ""
    platform: str = ""
    description: str = ""
    metadata: dict[str, Any] = {}


class BugReportConfirmResponse(BaseModel):
    bug_id: str


class BugReportItem(BaseModel):
    bug_id: str
    user_id: str | None = None
    user_email: str | None = None
    oss_key: str
    file_size_bytes: int
    app_version: str
    platform: str
    description: str
    metadata: dict[str, Any]
    download_url: str | None = None
    created_at: datetime


class BugReportListResponse(BaseModel):
    reports: list[BugReportItem]
    total: int
