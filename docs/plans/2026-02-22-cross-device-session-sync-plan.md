# Cross-Device Session Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Sync turn history, CA memory, and dynamic reports to the cloud backend after every turn, so a user who logs in on a new device silently recovers their full session state.

**Architecture:** Sidecar-direct sync — desktop registers a session with the backend (gets a `session_id`), passes it + JWT to the sidecar at session create time. After each turn completes, sidecar POSTs turn data + PUTs memory + report to the backend. Desktop checks for cloud state before creating a new session (WeChat-style silent restore). Workspace `.py`/`.ipynb` files are submitted explicitly via a Submit button, uploaded directly to OSS using a presigned URL, and tracked in a `user_submitted_files` table with a 100MB per-user quota.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (backend), Alembic (migrations), oss2 presigned PUT (file upload), httpx (sidecar HTTP calls), React + TypeScript (desktop)

**Design doc:** `docs/plans/2026-02-22-cross-device-session-sync-design.md`

---

## Task 1: Add SQLAlchemy models for session sync tables

**Files:**
- Modify: `llm-course-backend/app/models.py` (append after line 147)

**Step 1: Add the four new model classes**

Append to the end of `app/models.py`:

```python
class LearningSession(Base):
    __tablename__ = "learning_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    chapter_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    course_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SessionTurnHistory(Base):
    __tablename__ = "session_turn_history"
    __table_args__ = (UniqueConstraint("session_id", "turn_index", name="uq_turn_session_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("learning_sessions.session_id"), nullable=False, index=True)
    chapter_id: Mapped[str] = mapped_column(String(128), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    companion_response: Mapped[str] = mapped_column(Text, nullable=False)
    turn_outcome: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SessionMemoryState(Base):
    __tablename__ = "session_memory_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("learning_sessions.session_id"), nullable=False, unique=True)
    chapter_id: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SessionDynamicReport(Base):
    __tablename__ = "session_dynamic_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("learning_sessions.session_id"), nullable=False, unique=True)
    chapter_id: Mapped[str] = mapped_column(String(128), nullable=False)
    report_md: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserSubmittedFile(Base):
    __tablename__ = "user_submitted_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    oss_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

**Step 2: Commit**

```bash
cd llm-course-backend
git add app/models.py
git commit -m "feat: add LearningSession, SessionTurnHistory, SessionMemoryState, SessionDynamicReport, UserSubmittedFile models"
```

---

## Task 2: Write the Alembic migration

**Files:**
- Create: `llm-course-backend/migrations/versions/20260222_0005_add_session_sync_tables.py`

**Step 1: Create the migration file**

```python
"""add session sync tables

Revision ID: 20260222_0005
Revises: 20260222_0004
Create Date: 2026-02-22 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "20260222_0005"
down_revision = "20260222_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_sessions",
        sa.Column("session_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("course_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_sessions_user_id", "learning_sessions", ["user_id"])
    op.create_index("ix_learning_sessions_chapter_id", "learning_sessions", ["chapter_id"])

    op.create_table(
        "session_turn_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.session_id"), nullable=False),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("companion_response", sa.Text(), nullable=False),
        sa.Column("turn_outcome", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "turn_index", name="uq_turn_session_index"),
    )
    op.create_index("ix_session_turn_history_user_id", "session_turn_history", ["user_id"])
    op.create_index("ix_session_turn_history_session_id", "session_turn_history", ["session_id"])

    op.create_table(
        "session_memory_state",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.session_id"), nullable=False, unique=True),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("memory_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "session_dynamic_report",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.session_id"), nullable=False, unique=True),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("report_md", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "user_submitted_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("oss_key", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_submitted_files_user_id", "user_submitted_files", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_submitted_files")
    op.drop_table("session_dynamic_report")
    op.drop_table("session_memory_state")
    op.drop_table("session_turn_history")
    op.drop_table("learning_sessions")
```

**Step 2: Run the migration against a local DB to verify it applies cleanly**

```bash
cd llm-course-backend
uv run alembic upgrade head
```

Expected: no errors, all 5 tables created.

**Step 3: Commit**

```bash
git add migrations/versions/20260222_0005_add_session_sync_tables.py
git commit -m "feat: migration — add session sync tables"
```

---

## Task 3: Add Pydantic schemas for session sync

**Files:**
- Create: `llm-course-backend/app/schemas/sessions.py`

**Step 1: Create the file**

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel


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


# ── Workspace file submission ─────────────────────────────────────────────────

USER_QUOTA_BYTES = 100 * 1024 * 1024  # 100 MB


class UploadUrlRequest(BaseModel):
    chapter_id: str
    filename: str
    file_size_bytes: int


class UploadUrlResponse(BaseModel):
    presigned_url: str
    oss_key: str


class ConfirmUploadRequest(BaseModel):
    oss_key: str
    filename: str
    chapter_id: str
    file_size_bytes: int


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
    download_url: str | None = None


class SubmittedFilesResponse(BaseModel):
    files: list[SubmittedFileItem]
    quota_used_bytes: int
    quota_limit_bytes: int
```

**Step 2: Commit**

```bash
git add app/schemas/sessions.py
git commit -m "feat: add Pydantic schemas for session sync endpoints"
```

---

## Task 4: Implement the sessions API router (backend)

**Files:**
- Create: `llm-course-backend/app/api/routes/sessions.py`

**Step 1: Create the router**

```python
"""Session sync endpoints — called by desktop and sidecar."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import LearningSession, SessionDynamicReport, SessionMemoryState, SessionTurnHistory, UserSubmittedFile
from app.schemas.sessions import (
    AppendTurnRequest,
    ConfirmUploadRequest,
    ConfirmUploadResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    SessionStateResponse,
    SubmittedFileItem,
    SubmittedFilesResponse,
    TurnRecord,
    UploadUrlRequest,
    UploadUrlResponse,
    UpsertMemoryRequest,
    UpsertReportRequest,
    USER_QUOTA_BYTES,
)
from app.services.oss import oss_service

router = APIRouter(prefix="/v1", tags=["sessions"])


# ── Session registration ──────────────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/sessions", response_model=CreateSessionResponse, status_code=201)
def create_session(
    chapter_id: str,
    payload: CreateSessionRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> CreateSessionResponse:
    session_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    row = LearningSession(
        session_id=session_id,
        user_id=current_user.id,
        chapter_id=chapter_id,
        course_id=payload.course_id,
        created_at=now,
        last_active_at=now,
    )
    db.add(row)
    db.commit()
    return CreateSessionResponse(session_id=session_id, created_at=now)


# ── Turn append ───────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/turns", status_code=201)
def append_turn(
    session_id: str,
    payload: AppendTurnRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    _require_session_owner(db, session_id, current_user.id)

    # Upsert: ignore duplicates (idempotent — sidecar may retry)
    existing = db.execute(
        select(SessionTurnHistory).where(
            SessionTurnHistory.session_id == session_id,
            SessionTurnHistory.turn_index == payload.turn_index,
        )
    ).scalars().first()

    if not existing:
        row = SessionTurnHistory(
            user_id=current_user.id,
            session_id=session_id,
            chapter_id=payload.chapter_id,
            turn_index=payload.turn_index,
            user_message=payload.user_message,
            companion_response=payload.companion_response,
            turn_outcome=payload.turn_outcome,
        )
        db.add(row)

    # Update last_active_at
    session = db.get(LearningSession, session_id)
    session.last_active_at = datetime.now(timezone.utc)
    db.commit()
    return {"accepted": True}


# ── Memory upsert ─────────────────────────────────────────────────────────────

@router.put("/sessions/{session_id}/memory", status_code=200)
def upsert_memory(
    session_id: str,
    payload: UpsertMemoryRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    _require_session_owner(db, session_id, current_user.id)

    row = db.execute(
        select(SessionMemoryState).where(SessionMemoryState.session_id == session_id)
    ).scalars().first()

    if row:
        row.memory_json = payload.memory_json
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = SessionMemoryState(
            user_id=current_user.id,
            session_id=session_id,
            chapter_id=payload.chapter_id,
            memory_json=payload.memory_json,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(row)

    db.commit()
    return {"accepted": True}


# ── Report upsert ─────────────────────────────────────────────────────────────

@router.put("/sessions/{session_id}/report", status_code=200)
def upsert_report(
    session_id: str,
    payload: UpsertReportRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    _require_session_owner(db, session_id, current_user.id)

    row = db.execute(
        select(SessionDynamicReport).where(SessionDynamicReport.session_id == session_id)
    ).scalars().first()

    if row:
        row.report_md = payload.report_md
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = SessionDynamicReport(
            user_id=current_user.id,
            session_id=session_id,
            chapter_id=payload.chapter_id,
            report_md=payload.report_md,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(row)

    db.commit()
    return {"accepted": True}


# ── Recovery fetch ────────────────────────────────────────────────────────────

@router.get("/chapters/{chapter_id}/session-state", response_model=SessionStateResponse)
def get_session_state(
    chapter_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SessionStateResponse:
    # Find the most recent session for this user + chapter
    session = db.execute(
        select(LearningSession)
        .where(LearningSession.user_id == current_user.id, LearningSession.chapter_id == chapter_id)
        .order_by(LearningSession.last_active_at.desc())
        .limit(1)
    ).scalars().first()

    if not session:
        return SessionStateResponse(has_data=False)

    turns = db.execute(
        select(SessionTurnHistory)
        .where(SessionTurnHistory.session_id == session.session_id)
        .order_by(SessionTurnHistory.turn_index)
    ).scalars().all()

    memory_row = db.execute(
        select(SessionMemoryState).where(SessionMemoryState.session_id == session.session_id)
    ).scalars().first()

    report_row = db.execute(
        select(SessionDynamicReport).where(SessionDynamicReport.session_id == session.session_id)
    ).scalars().first()

    if not turns and not memory_row:
        return SessionStateResponse(has_data=False)

    return SessionStateResponse(
        has_data=True,
        session_id=session.session_id,
        turns=[
            TurnRecord(
                turn_index=t.turn_index,
                user_message=t.user_message,
                companion_response=t.companion_response,
                turn_outcome=t.turn_outcome,
                created_at=t.created_at,
            )
            for t in turns
        ],
        memory=memory_row.memory_json if memory_row else {},
        report_md=report_row.report_md if report_row else None,
    )


# ── Workspace file submission ─────────────────────────────────────────────────

@router.post("/storage/workspace/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    payload: UploadUrlRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> UploadUrlResponse:
    used = _quota_used(db, current_user.id)
    if used + payload.file_size_bytes > USER_QUOTA_BYTES:
        raise ApiError(
            status_code=409,
            code=ErrorCode.QUOTA_EXCEEDED,
            message=f"存储空间不足 (已用 {used // (1024*1024)}MB / 100MB)",
        )

    oss_key = f"user/{current_user.id}/workspace/{payload.chapter_id}/{payload.filename}"

    if not oss_service.is_enabled():
        # Dev fallback: return a dummy URL; actual upload will fail gracefully
        return UploadUrlResponse(presigned_url="http://localhost/dev-no-oss", oss_key=oss_key)

    presigned_url = oss_service.sign_put_url(oss_key, expires_seconds=300)
    return UploadUrlResponse(presigned_url=presigned_url, oss_key=oss_key)


@router.post("/storage/workspace/confirm", response_model=ConfirmUploadResponse, status_code=201)
def confirm_upload(
    payload: ConfirmUploadRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ConfirmUploadResponse:
    row = UserSubmittedFile(
        user_id=current_user.id,
        session_id="",          # session_id not required for file tracking
        chapter_id=payload.chapter_id,
        filename=payload.filename,
        oss_key=payload.oss_key,
        file_size_bytes=payload.file_size_bytes,
    )
    db.add(row)
    db.commit()
    used = _quota_used(db, current_user.id)
    return ConfirmUploadResponse(quota_used_bytes=used, quota_limit_bytes=USER_QUOTA_BYTES)


@router.get("/storage/workspace/files", response_model=SubmittedFilesResponse)
def list_submitted_files(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> SubmittedFilesResponse:
    rows = db.execute(
        select(UserSubmittedFile)
        .where(UserSubmittedFile.user_id == current_user.id)
        .order_by(UserSubmittedFile.submitted_at.desc())
    ).scalars().all()

    items = []
    for r in rows:
        download_url = oss_service.resolve_download_url(r.oss_key) if oss_service.is_enabled() else None
        items.append(SubmittedFileItem(
            id=r.id,
            filename=r.filename,
            chapter_id=r.chapter_id,
            oss_key=r.oss_key,
            file_size_bytes=r.file_size_bytes,
            submitted_at=r.submitted_at,
            download_url=download_url,
        ))

    used = _quota_used(db, current_user.id)
    return SubmittedFilesResponse(files=items, quota_used_bytes=used, quota_limit_bytes=USER_QUOTA_BYTES)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_session_owner(db: Session, session_id: str, user_id: uuid.UUID) -> LearningSession:
    session = db.get(LearningSession, session_id)
    if not session:
        raise ApiError(status_code=404, code=ErrorCode.SESSION_NOT_FOUND, message="Session not found")
    if session.user_id != user_id:
        raise ApiError(status_code=403, code=ErrorCode.SESSION_ACCESS_DENIED, message="Access denied")
    return session


def _quota_used(db: Session, user_id: uuid.UUID) -> int:
    result = db.execute(
        select(func.coalesce(func.sum(UserSubmittedFile.file_size_bytes), 0))
        .where(UserSubmittedFile.user_id == user_id)
    ).scalar()
    return int(result)
```

**Step 2: Commit**

```bash
git add app/api/routes/sessions.py
git commit -m "feat: add session sync API router (turns, memory, report, file upload)"
```

---

## Task 5: Add error codes + OSS sign_put_url helper

**Files:**
- Modify: `llm-course-backend/app/core/error_codes.py`
- Modify: `llm-course-backend/app/services/oss.py`

**Step 1: Add missing error codes to `error_codes.py`**

Add to the ErrorCode enum/class (check existing style):

```python
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
SESSION_ACCESS_DENIED = "SESSION_ACCESS_DENIED"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
```

**Step 2: Add `sign_put_url` method to `OSSService` (in `app/services/oss.py`)**

After the `_try_sign_download_url` method (around line 210), add:

```python
def sign_put_url(self, key: str, expires_seconds: int = 300) -> str:
    """Return a presigned PUT URL for direct client upload."""
    s = self._settings
    if not (s.oss_access_key_id and s.oss_access_key_secret and s.oss_bucket_name and s.oss_endpoint):
        raise RuntimeError("OSS credentials not configured")
    try:
        import oss2
        auth = oss2.Auth(s.oss_access_key_id, s.oss_access_key_secret)
        bucket = oss2.Bucket(auth, f"https://{s.oss_endpoint}", s.oss_bucket_name)
        return bucket.sign_url("PUT", key, expires_seconds)
    except Exception as exc:
        raise RuntimeError(f"Failed to generate presigned PUT URL: {exc}") from exc
```

**Step 3: Commit**

```bash
git add app/core/error_codes.py app/services/oss.py
git commit -m "feat: add SESSION_NOT_FOUND/QUOTA_EXCEEDED error codes and sign_put_url OSS helper"
```

---

## Task 6: Register the sessions router in main.py

**Files:**
- Modify: `llm-course-backend/app/main.py`

**Step 1: Add import**

On line 9, change:
```python
from app.api.routes import admin_bundles, admin_courses, analytics, auth, courses, me, progress, updates, upload
```
To:
```python
from app.api.routes import admin_bundles, admin_courses, analytics, auth, courses, me, progress, sessions, updates, upload
```

**Step 2: Register the router**

After line 65 (`app.include_router(analytics.router)`), add:
```python
app.include_router(sessions.router)
```

**Step 3: Verify the app starts**

```bash
cd llm-course-backend
docker compose up --build -d
curl http://localhost:10723/healthz
```

Expected: `{"status": "ok"}`

**Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: register sessions router in main.py"
```

---

## Task 7: Add post-turn sync to the sidecar

**Files:**
- Modify: `llm-course-sidecar/src/sidecar/main.py`

**Step 1: Extend `CreateSessionRequest` with sync fields (around line 574)**

Change:
```python
class CreateSessionRequest(BaseModel):
    """Request to create a new learning session."""

    chapter_id: str = Field(
        default="ch0_pandas_basics", description="Chapter identifier"
    )
    desktop_context: Optional[DesktopContext] = Field(
        default=None,
        description="Desktop-provided bundle and prompt resolution context",
    )
```

To:
```python
class CreateSessionRequest(BaseModel):
    """Request to create a new learning session."""

    chapter_id: str = Field(
        default="ch0_pandas_basics", description="Chapter identifier"
    )
    desktop_context: Optional[DesktopContext] = Field(
        default=None,
        description="Desktop-provided bundle and prompt resolution context",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Backend-registered session ID; if provided, sidecar uses this instead of generating one",
    )
    backend_url: Optional[str] = Field(
        default=None,
        description="Backend base URL for post-turn sync (e.g. http://47.93.151.131:10723)",
    )
    auth_token: Optional[str] = Field(
        default=None,
        description="JWT forwarded from desktop for authenticating backend sync calls",
    )
```

**Step 2: Store sync config in a module-level dict (near `session_orchestrators`, around line 200)**

Find where `session_orchestrators: Dict[str, Orchestrator] = {}` is defined and add below it:

```python
# Maps session_id → sync config passed at create time
session_sync_config: Dict[str, Dict[str, str]] = {}
```

**Step 3: In `create_session` (around line 882), store backend config after session creation**

After `session_orchestrators[session_id] = orchestrator`, add:

```python
if request.backend_url and request.auth_token:
    session_sync_config[session_id] = {
        "backend_url": request.backend_url.rstrip("/"),
        "auth_token": request.auth_token,
    }
```

Also, if `request.session_id` is provided, use it as the session_id instead of the orchestrator-generated one. Find where `session_id = await orchestrator.create_session(request.chapter_id)` is called. Check if the `Orchestrator.create_session` accepts a pre-set session_id. If it does, pass `request.session_id`. If not, after `session_id = await orchestrator.create_session(...)`, add a rename step — or pass the `session_id` through the orchestrator's session naming.

> **Note:** If the orchestrator always generates its own UUID, you may need to pass `session_id=request.session_id` to `orchestrator.create_session()`. Check the orchestrator source and adapt accordingly. The simplest safe approach: if `request.session_id` is provided and the new session_id differs, move the session directory to the requested session_id path and update `session_orchestrators`.

**Step 4: Add `_sync_turn_to_backend` async helper (add near the top of the route handlers, before `create_session`)**

```python
async def _sync_turn_to_backend(
    session_id: str,
    chapter_id: str,
    turn_index: int,
    user_message: str,
    companion_response: str,
    turn_outcome: dict,
    memo_json: dict,
    report_md: str,
) -> None:
    """Best-effort post-turn sync to backend. Failures are logged but never raised."""
    cfg = session_sync_config.get(session_id)
    if not cfg:
        return
    base = cfg["backend_url"]
    headers = {"Authorization": f"Bearer {cfg['auth_token']}"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{base}/v1/sessions/{session_id}/turns",
                json={
                    "chapter_id": chapter_id,
                    "turn_index": turn_index,
                    "user_message": user_message,
                    "companion_response": companion_response,
                    "turn_outcome": turn_outcome,
                },
                headers=headers,
            )
            await client.put(
                f"{base}/v1/sessions/{session_id}/memory",
                json={"chapter_id": chapter_id, "memory_json": memo_json},
                headers=headers,
            )
            await client.put(
                f"{base}/v1/sessions/{session_id}/report",
                json={"chapter_id": chapter_id, "report_md": report_md},
                headers=headers,
            )
    except Exception as exc:
        logger.warning("Backend sync failed for session %s turn %d: %s", session_id, turn_index, exc)
```

**Step 5: Call `_sync_turn_to_backend` after `process_turn_stream` completes**

In `send_message_stream` → `event_generator()`, after the `async for event in orchestrator.process_turn_stream(...)` loop completes (around line 1003, before yielding `complete`), add:

```python
# Post-turn sync (best-effort, fire-and-forget)
try:
    state = orchestrator.storage.load_state(session_id)
    turn_history = orchestrator.storage.load_turn_history(session_id)
    latest_turn = turn_history[-1] if turn_history else {}
    memo = {}
    try:
        memo = orchestrator.storage.load_memo_digest(session_id) or {}
    except Exception:
        pass
    report_md = ""
    try:
        report_path = orchestrator.storage.get_session_path(session_id) / "dynamic_report.md"
        if report_path.exists():
            report_md = report_path.read_text(encoding="utf-8")
    except Exception:
        pass
    asyncio.create_task(_sync_turn_to_backend(
        session_id=session_id,
        chapter_id=state.chapter_id,
        turn_index=state.turn_index,
        user_message=latest_turn.get("user_message", ""),
        companion_response=latest_turn.get("companion_response", ""),
        turn_outcome=latest_turn.get("turn_outcome", {}),
        memo_json=memo if isinstance(memo, dict) else {},
        report_md=report_md,
    ))
except Exception as exc:
    logger.warning("Failed to schedule backend sync: %s", exc)
```

> **Note:** Check exact method names on `orchestrator.storage` — use `load_turn_history`, `load_state`, `load_memo_digest`, `get_session_path` per the sidecar's actual storage API. Adapt names as needed.

**Step 6: Clean up sync config on session end**

In `end_session` handler (around line 1074), after the session ends, add:

```python
session_sync_config.pop(session_id, None)
```

**Step 7: Commit**

```bash
cd llm-course-sidecar
git add src/sidecar/main.py
git commit -m "feat: add post-turn backend sync to sidecar (session_id/auth_token forwarding)"
```

---

## Task 8: Update the desktop — register session with backend before starting sidecar

**Files:**
- Modify: `llm-course-desktop/services/runtimeManager.ts`
- Modify: `llm-course-desktop/services/backendClient.ts`

**Step 1: Add `createBackendSession` to `backendClient.ts`**

Find the `backendClient` service and add:

```typescript
export async function createBackendSession(chapterId: string, courseId?: string): Promise<{ session_id: string }> {
  return apiFetch<{ session_id: string }>(`/v1/chapters/${chapterId}/sessions`, {
    method: 'POST',
    body: JSON.stringify({ course_id: courseId ?? null }),
  });
}
```

**Step 2: Add `fetchSessionState` to `backendClient.ts`**

```typescript
export interface SessionStateResult {
  has_data: boolean;
  session_id?: string;
  turns?: Array<{
    turn_index: number;
    user_message: string;
    companion_response: string;
    turn_outcome: Record<string, unknown>;
    created_at: string;
  }>;
  memory?: Record<string, unknown>;
  report_md?: string;
}

export async function fetchSessionState(chapterId: string): Promise<SessionStateResult> {
  return apiFetch<SessionStateResult>(`/v1/chapters/${chapterId}/session-state`);
}
```

**Step 3: Update `createSession` in `runtimeManager.ts`**

Find the current `createSession(chapterId)` call. Wrap it to:

1. Call `createBackendSession(chapterId)` to get `backendSessionId`
2. Pass `session_id`, `backend_url`, `auth_token` to sidecar `POST /api/session/new`

```typescript
async createSession(chapterId: string, courseId?: string): Promise<{ sessionId: string; initialMessage: string }> {
  // Step 1: Register session with backend (best-effort — fall back to local-only if fails)
  let backendSessionId: string | undefined;
  try {
    const result = await createBackendSession(chapterId, courseId);
    backendSessionId = result.session_id;
  } catch (err) {
    console.warn('[runtimeManager] Failed to register session with backend, continuing local-only:', err);
  }

  // Step 2: Create sidecar session, forwarding backend credentials
  const token = getAuthToken(); // however the current code gets the JWT
  const body: Record<string, unknown> = {
    chapter_id: chapterId,
    // ... existing desktop_context fields
  };
  if (backendSessionId) {
    body.session_id = backendSessionId;
    body.backend_url = BACKEND_BASE_URL;
    body.auth_token = token;
  }

  const res = await sidecarFetch('/api/session/new', { method: 'POST', body: JSON.stringify(body) });
  return { sessionId: res.session_id, initialMessage: res.initial_message };
}
```

> **Note:** Adapt to the exact existing `runtimeManager.ts` structure. Find where `fetch('/api/session/new', ...)` is currently called and extend that call site.

**Step 4: Commit**

```bash
cd llm-course-desktop
git add services/runtimeManager.ts services/backendClient.ts
git commit -m "feat: register backend session before sidecar session create"
```

---

## Task 9: Desktop recovery flow — restore session on new device

**Files:**
- Modify: `llm-course-desktop/components/CentralChat.tsx`

**Step 1: Add `fetchSessionState` call before `handleStartChapter`**

In `CentralChat.tsx`, at the point where the chapter is opened (before calling `handleStartChapter` / `runtimeManager.createSession`), add a recovery check:

```typescript
const [recovering, setRecovering] = useState(false);

// Run once when chapter opens, before user clicks "Start"
useEffect(() => {
  (async () => {
    // Only check if we don't already have a local session
    if (sessionId || sessionStarted) return;
    try {
      const state = await fetchSessionState(chapter.id);
      if (!state.has_data || !state.turns?.length) return;

      setRecovering(true);
      // Write recovered data to sidecar via IPC (new electron IPC handler)
      await window.tutorApp.restoreSessionState({
        sessionId: state.session_id!,
        turns: state.turns!,
        memoryJson: state.memory ?? {},
        reportMd: state.report_md ?? '',
      });
      // Reattach the session in the sidecar
      await sidecarFetch(`/api/session/${state.session_id}/reattach`, {
        method: 'POST',
        body: JSON.stringify({ desktop_context: buildDesktopContext() }),
      });
      // Show restored history
      setSessionId(state.session_id!);
      setMessages(state.turns!.map(t => [
        { role: 'user' as const, text: t.user_message },
        { role: 'model' as const, text: t.companion_response },
      ]).flat());
      setSessionStarted(true);
    } catch (err) {
      console.warn('[CentralChat] Recovery check failed, starting fresh:', err);
    } finally {
      setRecovering(false);
    }
  })();
}, [chapter.id]);
```

**Step 2: Show recovery overlay**

In the JSX, replace the existing start-chapter loading state to also handle `recovering`:

```tsx
{recovering && (
  <div className="flex flex-col items-center gap-3">
    <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />
    <p className="text-sm text-gray-500">正在恢复学习记录...</p>
  </div>
)}
```

**Step 3: Commit**

```bash
git add components/CentralChat.tsx
git commit -m "feat: auto-restore session state from backend on new device"
```

---

## Task 10: Electron IPC — `restoreSessionState` handler

**Files:**
- Modify: `llm-course-desktop/electron/main.mjs`
- Modify: `llm-course-desktop/electron/preload.mjs`
- Modify: `llm-course-desktop/electron/preload.cjs`
- Modify: `llm-course-desktop/types.ts`

**Step 1: Add IPC handler in `main.mjs`**

The desktop needs to write recovered session files to the sidecar's sessions directory so the sidecar can reattach them. Add:

```javascript
ipcMain.handle('session:restore', async (_event, { sessionId, turns, memoryJson, reportMd }) => {
  const sessionsDir = path.join(app.getPath('userData'), 'sidecar_sessions', sessionId);
  await fs.mkdir(sessionsDir, { recursive: true });

  const turnsDir = path.join(sessionsDir, 'turns');
  await fs.mkdir(turnsDir, { recursive: true });

  // Write each turn as individual files (matching sidecar's storage format)
  for (const turn of turns) {
    const idx = String(turn.turn_index).padStart(3, '0');
    await fs.writeFile(path.join(turnsDir, `${idx}_user.txt`), turn.user_message, 'utf8');
    await fs.writeFile(path.join(turnsDir, `${idx}_companion.txt`), turn.companion_response, 'utf8');
    await fs.writeFile(path.join(turnsDir, `${idx}_turn_outcome.json`), JSON.stringify(turn.turn_outcome ?? {}), 'utf8');
  }

  // Write memory
  if (Object.keys(memoryJson).length > 0) {
    await fs.writeFile(path.join(sessionsDir, 'memo_digest.json'), JSON.stringify(memoryJson), 'utf8');
  }

  // Write dynamic report
  if (reportMd) {
    await fs.writeFile(path.join(sessionsDir, 'dynamic_report.md'), reportMd, 'utf8');
  }

  return { ok: true };
});
```

> **Note:** The exact `sessionsDir` path must match what the sidecar uses. Check `llm-course-desktop/electron/main.mjs` for where `sessions_root` is set for the sidecar process (likely `userData/sessions` or similar). Use the same path.

**Step 2: Expose in both preload files**

In `preload.mjs` and `preload.cjs`:
```javascript
restoreSessionState: (payload) => ipcRenderer.invoke('session:restore', payload),
```

**Step 3: Add type in `types.ts`**

```typescript
restoreSessionState: (payload: {
  sessionId: string;
  turns: Array<{ turn_index: number; user_message: string; companion_response: string; turn_outcome: Record<string, unknown> }>;
  memoryJson: Record<string, unknown>;
  reportMd: string;
}) => Promise<{ ok: boolean }>;
```

**Step 4: Commit**

```bash
cd llm-course-desktop
git add electron/main.mjs electron/preload.mjs electron/preload.cjs types.ts
git commit -m "feat: add session:restore IPC handler for cross-device recovery"
```

---

## Task 11: File submit UX — Submit button in code editor

**Files:**
- Modify: `llm-course-desktop/components/CentralChat.tsx` (or wherever the code editor panel lives)
- Modify: `llm-course-desktop/services/backendClient.ts`

**Step 1: Add workspace file submit helpers to `backendClient.ts`**

```typescript
export async function getWorkspaceUploadUrl(params: {
  chapterId: string;
  filename: string;
  fileSizeBytes: number;
}): Promise<{ presigned_url: string; oss_key: string }> {
  return apiFetch('/v1/storage/workspace/upload-url', {
    method: 'POST',
    body: JSON.stringify({ chapter_id: params.chapterId, filename: params.filename, file_size_bytes: params.fileSizeBytes }),
  });
}

export async function confirmWorkspaceUpload(params: {
  ossKey: string;
  filename: string;
  chapterId: string;
  fileSizeBytes: number;
}): Promise<{ quota_used_bytes: number; quota_limit_bytes: number }> {
  return apiFetch('/v1/storage/workspace/confirm', {
    method: 'POST',
    body: JSON.stringify({ oss_key: params.ossKey, filename: params.filename, chapter_id: params.chapterId, file_size_bytes: params.fileSizeBytes }),
  });
}
```

**Step 2: Add `handleSubmitFile` in the code editor component**

In the file where Run button lives (likely a CodeEditor or WorkspacePanel component):

```typescript
const [submitting, setSubmitting] = useState(false);
const [submitDone, setSubmitDone] = useState(false);

const handleSubmitFile = async (filename: string, content: string) => {
  const blob = new Blob([content], { type: 'text/plain' });
  const fileSizeBytes = blob.size;
  setSubmitting(true);
  setSubmitDone(false);
  try {
    const { presigned_url, oss_key } = await getWorkspaceUploadUrl({
      chapterId: chapter.id,
      filename,
      fileSizeBytes,
    });
    // Direct PUT to OSS
    await fetch(presigned_url, { method: 'PUT', body: blob });
    // Confirm with backend
    await confirmWorkspaceUpload({ ossKey: oss_key, filename, chapterId: chapter.id, fileSizeBytes });
    setSubmitDone(true);
    setTimeout(() => setSubmitDone(false), 2000);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes('409') || msg.toLowerCase().includes('quota')) {
      toast.error('存储空间不足 (已用满 100MB)');
    } else {
      toast.error('提交失败，请重试');
    }
  } finally {
    setSubmitting(false);
  }
};
```

**Step 3: Add Submit button beside Run button in JSX**

```tsx
<button
  onClick={() => handleSubmitFile(currentFilename, currentContent)}
  disabled={submitting}
  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
             bg-green-50 text-green-700 hover:bg-green-100 border border-green-200
             disabled:opacity-40 transition-colors"
>
  {submitting ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
  {submitDone ? '已提交' : '提交'}
</button>
```

**Step 4: Commit**

```bash
git add components/CentralChat.tsx services/backendClient.ts
git commit -m "feat: add Submit button for workspace file upload to OSS"
```

---

## Task 12: End-to-end smoke test

**Step 1: Start backend with fresh DB**

```bash
cd llm-course-backend
docker compose up --build -d
uv run alembic upgrade head
```

**Step 2: Test session registration**

```bash
# Get auth token first
TOKEN=$(curl -s -X POST http://localhost:10723/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"student@example.com","password":"StrongPass123"}' | jq -r '.access_token')

# Register a session
curl -s -X POST http://localhost:10723/v1/chapters/ch0_pandas_basics/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"course_id": null}' | jq
```

Expected: `{ "session_id": "...", "created_at": "..." }`

**Step 3: Test turn append**

```bash
SESSION_ID=<from above>
curl -s -X POST http://localhost:10723/v1/sessions/$SESSION_ID/turns \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"chapter_id":"ch0","turn_index":0,"user_message":"hello","companion_response":"hi there","turn_outcome":{}}' | jq
```

Expected: `{ "accepted": true }`

**Step 4: Test recovery fetch**

```bash
curl -s http://localhost:10723/v1/chapters/ch0_pandas_basics/session-state \
  -H "Authorization: Bearer $TOKEN" | jq
```

Expected: `{ "has_data": true, "session_id": "...", "turns": [...], ... }`

**Step 5: Run integration tests**

```bash
cd llm-course-backend
RUN_INTEGRATION=1 BASE_URL=http://localhost:10723 uv run pytest -q tests/
```

Expected: all existing tests pass (session sync is additive — nothing removed).

**Step 6: Commit any test fixes**

```bash
git add .
git commit -m "fix: resolve any integration test regressions from session sync"
```

---

## Verification Checklist

- [ ] `uv run alembic upgrade head` creates all 5 new tables with correct constraints
- [ ] `POST /v1/chapters/{id}/sessions` returns a `session_id`
- [ ] `POST /v1/sessions/{id}/turns` is idempotent (duplicate turn_index → no error)
- [ ] `GET /v1/chapters/{id}/session-state` returns `has_data: false` for a user with no sessions
- [ ] `GET /v1/chapters/{id}/session-state` returns all turns + memory + report after sync
- [ ] Sidecar fires sync calls after each turn (visible in sidecar logs)
- [ ] Sync failure does not break the turn (sidecar logs warning only)
- [ ] Desktop registers a backend session before calling sidecar
- [ ] On new device (no local session files), desktop shows "正在恢复学习记录..." and restores chat history
- [ ] Submit button in code editor uploads file to OSS and shows "已提交"
- [ ] 100MB quota is enforced (409 on exceed)
