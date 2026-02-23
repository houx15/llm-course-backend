"""Session sync endpoints — called by desktop and sidecar."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import (
    LearningSession,
    SessionDynamicReport,
    SessionMemoryState,
    SessionTurnHistory,
    User,
    UserSubmittedFile,
)
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

@router.post("/chapters/{chapter_id:path}/sessions", response_model=CreateSessionResponse, status_code=201)
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

    session_row = db.get(LearningSession, session_id)
    session_row.last_active_at = datetime.now(timezone.utc)
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

@router.get("/chapters/{chapter_id:path}/session-state", response_model=SessionStateResponse)
def get_session_state(
    chapter_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    course_id: str | None = Query(default=None),
) -> SessionStateResponse:
    stmt = (
        select(LearningSession)
        .where(
            LearningSession.user_id == current_user.id,
            LearningSession.chapter_id == chapter_id,
        )
        .order_by(LearningSession.last_active_at.desc())
        .limit(1)
    )
    if course_id:
        stmt = stmt.where(LearningSession.course_id == course_id)

    session = db.execute(stmt).scalars().first()

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
            message=f"存储空间不足 (已用 {used // (1024 * 1024)}MB / 100MB)",
        )

    oss_key = f"user/{current_user.id}/workspace/{payload.chapter_id}/{payload.filename}"
    required_headers = {"Content-Type": "application/octet-stream"}

    if not oss_service.is_enabled():
        return UploadUrlResponse(
            presigned_url="http://localhost/dev-no-oss",
            oss_key=oss_key,
            required_headers={},
        )

    presigned_url = oss_service.sign_put_url(
        oss_key,
        expires_seconds=300,
        headers=required_headers,
    )
    return UploadUrlResponse(
        presigned_url=presigned_url,
        oss_key=oss_key,
        required_headers=required_headers,
    )


@router.post("/storage/workspace/confirm", response_model=ConfirmUploadResponse, status_code=201)
def confirm_upload(
    payload: ConfirmUploadRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ConfirmUploadResponse:
    expected_prefix = f"user/{current_user.id}/workspace/{payload.chapter_id}/"
    if not payload.oss_key.startswith(expected_prefix):
        raise ApiError(
            status_code=400,
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid oss_key for current user/chapter",
        )

    # Serialize confirms per user so quota check + insert is atomic.
    db.execute(select(User.id).where(User.id == current_user.id).with_for_update()).scalar_one_or_none()
    used = _quota_used(db, current_user.id)
    if used + payload.file_size_bytes > USER_QUOTA_BYTES:
        raise ApiError(
            status_code=409,
            code=ErrorCode.QUOTA_EXCEEDED,
            message=f"存储空间不足 (已用 {used // (1024 * 1024)}MB / 100MB)",
        )

    row = UserSubmittedFile(
        user_id=current_user.id,
        session_id=payload.session_id,
        chapter_id=payload.chapter_id,
        filename=payload.filename,
        oss_key=payload.oss_key,
        file_size_bytes=payload.file_size_bytes,
    )
    db.add(row)
    db.commit()
    return ConfirmUploadResponse(
        quota_used_bytes=used + payload.file_size_bytes,
        quota_limit_bytes=USER_QUOTA_BYTES,
    )


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
        items.append(
            SubmittedFileItem(
                id=r.id,
                filename=r.filename,
                chapter_id=r.chapter_id,
                oss_key=r.oss_key,
                file_size_bytes=r.file_size_bytes,
                submitted_at=r.submitted_at,
                download_url=download_url,
            )
        )

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
        select(func.coalesce(func.sum(UserSubmittedFile.file_size_bytes), 0)).where(
            UserSubmittedFile.user_id == user_id
        )
    ).scalar()
    return int(result)
