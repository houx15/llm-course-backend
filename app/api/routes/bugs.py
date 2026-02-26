"""Bug report endpoints: presigned upload URL + confirm, and admin listing."""

import random
import string

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette import status

from app.api.admin_auth import require_admin_key
from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import BugReport, User
from app.schemas.bugs import (
    BugReportConfirmRequest,
    BugReportConfirmResponse,
    BugReportItem,
    BugReportListResponse,
    BugReportUrlRequest,
    BugReportUrlResponse,
)
from app.services.oss import oss_service

router = APIRouter(prefix="/v1", tags=["bugs"])


def _generate_bug_id() -> str:
    """Generate a short human-readable bug ID like BUG-A3F2K1."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=6))
    return f"BUG-{suffix}"


def _unique_bug_id(db: Session) -> str:
    """Generate a bug ID that doesn't already exist."""
    for _ in range(10):
        bug_id = _generate_bug_id()
        exists = db.execute(select(BugReport.id).where(BugReport.bug_id == bug_id)).scalar_one_or_none()
        if not exists:
            return bug_id
    raise ApiError(status_code=500, code="INTERNAL_ERROR", message="Failed to generate unique bug ID")


# ── User endpoints ──────────────────────────────────────────────────────────


@router.post("/bugs/report-url", response_model=BugReportUrlResponse)
async def get_bug_report_url(
    payload: BugReportUrlRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> BugReportUrlResponse:
    """Get a presigned URL to upload a bug report log file."""
    bug_id = _unique_bug_id(db)
    oss_key = f"bug-reports/{bug_id}/logs.json"
    required_headers = {"Content-Type": "application/json"}

    if not oss_service.is_enabled():
        return BugReportUrlResponse(
            bug_id=bug_id,
            presigned_url="http://localhost/dev-no-oss",
            oss_key=oss_key,
            required_headers={},
        )

    presigned_url = oss_service.sign_put_url(
        oss_key,
        expires_seconds=300,
        headers=required_headers,
    )
    return BugReportUrlResponse(
        bug_id=bug_id,
        presigned_url=presigned_url,
        oss_key=oss_key,
        required_headers=required_headers,
    )


@router.post(
    "/bugs/confirm",
    response_model=BugReportConfirmResponse,
    status_code=status.HTTP_201_CREATED,
)
def confirm_bug_report(
    payload: BugReportConfirmRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> BugReportConfirmResponse:
    """Confirm a bug report upload and save metadata."""
    # Validate oss_key matches the bug_id
    expected_prefix = f"bug-reports/{payload.bug_id}/"
    if not payload.oss_key.startswith(expected_prefix):
        raise ApiError(
            status_code=400,
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid oss_key for this bug report",
        )

    row = BugReport(
        bug_id=payload.bug_id,
        user_id=current_user.id,
        oss_key=payload.oss_key,
        file_size_bytes=payload.file_size_bytes,
        app_version=payload.app_version,
        platform=payload.platform,
        description=payload.description,
        metadata_json=payload.metadata,
    )
    db.add(row)
    db.commit()

    return BugReportConfirmResponse(bug_id=payload.bug_id)


# ── Admin endpoints ─────────────────────────────────────────────────────────


def _to_bug_report_item(report: BugReport, user_email: str | None, download_url: str | None) -> BugReportItem:
    return BugReportItem(
        bug_id=report.bug_id,
        user_id=str(report.user_id) if report.user_id else None,
        user_email=user_email,
        oss_key=report.oss_key,
        file_size_bytes=report.file_size_bytes,
        app_version=report.app_version,
        platform=report.platform,
        description=report.description,
        metadata=report.metadata_json,
        download_url=download_url,
        created_at=report.created_at,
    )


@router.get(
    "/admin/bugs/reports",
    response_model=BugReportListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_bug_reports(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BugReportListResponse:
    """List recent bug reports (admin only)."""
    total = db.execute(select(func.count()).select_from(BugReport)).scalar() or 0

    rows = (
        db.execute(
            select(BugReport, User.email)
            .outerjoin(User, BugReport.user_id == User.id)
            .order_by(BugReport.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        .all()
    )

    reports = []
    for report, email in rows:
        download_url = oss_service.resolve_download_url(report.oss_key, expires_seconds=3600)
        reports.append(_to_bug_report_item(report, email, download_url))

    return BugReportListResponse(reports=reports, total=total)


@router.get(
    "/admin/bugs/reports/{bug_id}",
    response_model=BugReportItem,
    dependencies=[Depends(require_admin_key)],
)
def get_bug_report(
    bug_id: str,
    db: Session = Depends(get_db),
) -> BugReportItem:
    """Get a single bug report by bug ID (admin only)."""
    result = db.execute(
        select(BugReport, User.email)
        .outerjoin(User, BugReport.user_id == User.id)
        .where(BugReport.bug_id == bug_id)
    ).first()

    if not result:
        raise ApiError(
            status_code=404,
            code=ErrorCode.BUG_REPORT_NOT_FOUND,
            message=f"Bug report {bug_id} not found",
        )

    report, email = result
    download_url = oss_service.resolve_download_url(report.oss_key, expires_seconds=3600)
    return _to_bug_report_item(report, email, download_url)
