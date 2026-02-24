from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── Session registration ──────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    course_id: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: datetime


# ── Turn append ───────────────────────────────────────────────────────────────

class AppendTurnRequest(BaseModel):
    chapter_id: str
    turn_index: int
    user_message: str
    companion_response: str
    turn_outcome: dict[str, Any] = {}


# ── Memory upsert ─────────────────────────────────────────────────────────────

class UpsertMemoryRequest(BaseModel):
    chapter_id: str
    memory_json: dict[str, Any]
    agent_state: dict[str, Any] | None = None


# ── Report upsert ─────────────────────────────────────────────────────────────

class UpsertReportRequest(BaseModel):
    chapter_id: str
    report_md: str


# ── Recovery fetch ────────────────────────────────────────────────────────────

class TurnRecord(BaseModel):
    turn_index: int
    user_message: str
    companion_response: str
    turn_outcome: dict[str, Any]
    created_at: datetime


class SessionStateResponse(BaseModel):
    has_data: bool
    session_id: str | None = None
    turns: list[TurnRecord] = []
    memory: dict[str, Any] = {}
    report_md: str | None = None
    agent_state: dict[str, Any] | None = None


# ── Chapter sessions list ────────────────────────────────────────────────────


class SessionSummaryItem(BaseModel):
    session_id: str
    created_at: datetime
    last_active_at: datetime
    turn_count: int


class ChapterSessionsResponse(BaseModel):
    sessions: list[SessionSummaryItem]


# ── Workspace file submission ─────────────────────────────────────────────────

USER_QUOTA_BYTES = 100 * 1024 * 1024  # 100 MB


def _validate_workspace_filename(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("filename is required")
    if name != Path(name).name or "/" in name or "\\" in name:
        raise ValueError("invalid filename")
    return name


class UploadUrlRequest(BaseModel):
    chapter_id: str
    filename: str
    file_size_bytes: int = Field(gt=0)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return _validate_workspace_filename(value)


class UploadUrlResponse(BaseModel):
    presigned_url: str
    oss_key: str
    required_headers: dict[str, str] = {}


class ConfirmUploadRequest(BaseModel):
    oss_key: str
    filename: str
    chapter_id: str
    file_size_bytes: int = Field(gt=0)
    session_id: str = ""

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return _validate_workspace_filename(value)


class ConfirmUploadResponse(BaseModel):
    quota_used_bytes: int
    quota_limit_bytes: int


class SubmittedFileItem(BaseModel):
    id: int
    filename: str
    chapter_id: str
    oss_key: str
    file_size_bytes: int
    submitted_at: datetime
    updated_at: datetime | None = None
    download_url: str | None = None


class SubmittedFilesResponse(BaseModel):
    files: list[SubmittedFileItem]
    quota_used_bytes: int
    quota_limit_bytes: int


# ── Chapter workspace files (sync) ──────────────────────────────────────────

class ChapterFileItem(BaseModel):
    filename: str
    oss_key: str
    file_size_bytes: int
    updated_at: datetime
    download_url: str | None = None


class ChapterFilesResponse(BaseModel):
    files: list[ChapterFileItem]
