from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import CourseChapter, Enrollment
from app.schemas.updates import CheckAppRequest, CheckAppResponse, CheckChapterRequest, CheckChapterResolved, CheckChapterResponse
from app.services.update_service import check_bundle_required, latest_bundle_release

router = APIRouter(prefix="/v1/updates", tags=["updates"])


@router.post("/check-app", response_model=CheckAppResponse)
def check_app_updates(
    payload: CheckAppRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> CheckAppResponse:
    del current_user

    required = []
    optional = []

    # Core app agent bundle.
    app_release = latest_bundle_release(db, bundle_type="app_agents", scope_id="core")
    app_required = check_bundle_required(payload.installed.get("app_agents"), app_release)
    if app_required:
        required.append(app_required)

    # Shared experts bundle.
    experts_release = latest_bundle_release(db, bundle_type="experts_shared", scope_id="shared")
    experts_required = check_bundle_required(payload.installed.get("experts_shared"), experts_release)
    if experts_required:
        optional.append(experts_required)

    # Python runtime bundle (sidecar).
    # Try platform-specific scope first, then well-known generic scopes, then any python_runtime.
    platform_scope = (getattr(payload, "platform_scope", None) or "").strip()
    pr_scope_ids: list[str] = []
    if platform_scope:
        pr_scope_ids.append(platform_scope)
    pr_scope_ids.extend(["core", "default", "standard", "py312"])

    pr_release = None
    for scope in pr_scope_ids:
        pr_release = latest_bundle_release(db, bundle_type="python_runtime", scope_id=scope)
        if pr_release:
            break

    # Final fallback: any python_runtime bundle regardless of scope.
    if not pr_release:
        pr_release = latest_bundle_release(db, bundle_type="python_runtime")

    pr_descriptor = check_bundle_required(payload.installed.get("python_runtime"), pr_release)
    if pr_descriptor:
        required.append(pr_descriptor)

    return CheckAppResponse(required=required, optional=optional)


@router.post("/check-chapter", response_model=CheckChapterResponse)
def check_chapter_updates(
    payload: CheckChapterRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> CheckChapterResponse:
    enrollment = db.execute(
        select(Enrollment).where(
            Enrollment.user_id == current_user.id,
            Enrollment.course_id == payload.course_id,
            Enrollment.status == "active",
        )
    ).scalars().first()
    if not enrollment:
        raise ApiError(status_code=403, code=ErrorCode.COURSE_ACCESS_DENIED, message="Course not enrolled")

    chapter = db.execute(
        select(CourseChapter).where(
            CourseChapter.course_id == payload.course_id,
            CourseChapter.chapter_code == payload.chapter_id,
            CourseChapter.is_active.is_(True),
        )
    ).scalars().first()
    if not chapter:
        raise ApiError(status_code=404, code=ErrorCode.CHAPTER_NOT_FOUND, message="Chapter not found")

    required = []
    chapter_scope = f"{payload.course_id}/{payload.chapter_id}"
    chapter_release = latest_bundle_release(db, bundle_type="chapter", scope_id=chapter_scope)
    chapter_required = check_bundle_required(payload.installed.chapter_bundle, chapter_release)
    if chapter_required:
        required.append(chapter_required)

    required_experts: list[str] = []
    if chapter_release and isinstance(chapter_release.manifest_json, dict):
        values = chapter_release.manifest_json.get("required_experts", [])
        if isinstance(values, list):
            required_experts = [str(item) for item in values]

    for expert_id in required_experts:
        release = latest_bundle_release(db, bundle_type="experts", scope_id=expert_id)
        installed = payload.installed.experts.get(expert_id)
        descriptor = check_bundle_required(installed, release)
        if descriptor:
            required.append(descriptor)

    return CheckChapterResponse(
        required=required,
        resolved_chapter=CheckChapterResolved(
            course_id=payload.course_id,
            chapter_id=payload.chapter_id,
            required_experts=required_experts,
        ),
    )
