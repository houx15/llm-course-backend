from fastapi import APIRouter, Depends
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import BundleRelease, ChapterProgress, Course, CourseChapter, Enrollment
from app.schemas.courses import (
    ChapterItem,
    CourseChaptersResponse,
    CourseDetailResponse,
    CourseOverview,
    CourseSummary,
    CoursesMyResponse,
    JoinCourseRequest,
    JoinCourseResponse,
)

router = APIRouter(prefix="/v1/courses", tags=["courses"])


def _course_summary(course: Course, joined_at: str) -> CourseSummary:
    return CourseSummary(
        id=str(course.id),
        title=course.title,
        course_code=course.course_code,
        instructor=course.instructor,
        semester=course.semester,
        description=course.description,
        joined_at=joined_at,
    )


@router.get("/my", response_model=CoursesMyResponse)
def list_my_courses(current_user: CurrentUser, db: Session = Depends(get_db)) -> CoursesMyResponse:
    stmt = (
        select(Enrollment, Course)
        .join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.user_id == current_user.id, Enrollment.status == "active", Course.is_active.is_(True))
        .order_by(Enrollment.joined_at.desc())
    )
    rows = db.execute(stmt).all()

    courses = [_course_summary(course, enrollment.joined_at.isoformat()) for enrollment, course in rows]
    return CoursesMyResponse(courses=courses)


@router.post("/join", response_model=JoinCourseResponse)
def join_course(payload: JoinCourseRequest, current_user: CurrentUser, db: Session = Depends(get_db)) -> JoinCourseResponse:
    code = payload.invite_code.strip().upper()
    course = db.execute(
        select(Course).where(Course.invite_code == code, Course.is_active.is_(True))
    ).scalars().first()
    if not course:
        raise ApiError(status_code=404, code=ErrorCode.COURSE_NOT_FOUND, message="Invalid invite code")

    enrollment = db.execute(
        select(Enrollment).where(Enrollment.user_id == current_user.id, Enrollment.course_id == course.id)
    ).scalars().first()
    if not enrollment:
        enrollment = Enrollment(user_id=current_user.id, course_id=course.id, status="active")
        db.add(enrollment)
        db.commit()
        db.refresh(enrollment)

    return JoinCourseResponse(course=_course_summary(course, enrollment.joined_at.isoformat()))


@router.get("/{course_id}", response_model=CourseDetailResponse)
def get_course(course_id: str, current_user: CurrentUser, db: Session = Depends(get_db)) -> CourseDetailResponse:
    enrollment = db.execute(
        select(Enrollment).where(Enrollment.user_id == current_user.id, Enrollment.course_id == course_id, Enrollment.status == "active")
    ).scalars().first()
    if not enrollment:
        raise ApiError(status_code=403, code=ErrorCode.COURSE_ACCESS_DENIED, message="Course not enrolled")

    course = db.get(Course, course_id)
    if not course or not course.is_active:
        raise ApiError(status_code=404, code=ErrorCode.COURSE_NOT_FOUND, message="Course not found")

    return CourseDetailResponse(
        id=str(course.id),
        title=course.title,
        description=course.description,
        instructor=course.instructor,
        overview=CourseOverview(
            experience=course.overview_experience,
            gains=course.overview_gains,
            necessity=course.overview_necessity,
            journey=course.overview_journey,
        ),
    )


@router.get("/{course_id}/chapters", response_model=CourseChaptersResponse)
def list_course_chapters(course_id: str, current_user: CurrentUser, db: Session = Depends(get_db)) -> CourseChaptersResponse:
    enrollment = db.execute(
        select(Enrollment).where(Enrollment.user_id == current_user.id, Enrollment.course_id == course_id, Enrollment.status == "active")
    ).scalars().first()
    if not enrollment:
        raise ApiError(status_code=403, code=ErrorCode.COURSE_ACCESS_DENIED, message="Course not enrolled")

    chapters_all = db.execute(
        select(CourseChapter)
        .where(and_(CourseChapter.course_id == course_id, CourseChapter.is_active.is_(True)))
        .order_by(CourseChapter.sort_order.asc())
    ).scalars().all()
    if not chapters_all:
        return CourseChaptersResponse(course_id=course_id, chapters=[])

    # Look up latest bundle per chapter UUID scope
    bundle_by_chapter: dict[str, BundleRelease] = {}
    for ch in chapters_all:
        scope = str(ch.id)
        release = db.execute(
            select(BundleRelease)
            .where(BundleRelease.bundle_type == "chapter", BundleRelease.scope_id == scope)
            .order_by(BundleRelease.created_at.desc())
            .limit(1)
        ).scalars().first()
        if release:
            bundle_by_chapter[scope] = release

    # Only return chapters that have bundles
    chapters = [ch for ch in chapters_all if str(ch.id) in bundle_by_chapter]

    progress_rows = db.execute(
        select(ChapterProgress).where(ChapterProgress.user_id == current_user.id, ChapterProgress.course_id == course_id)
    ).scalars().all()
    progress_map = {str(row.chapter_id): row for row in progress_rows}

    from app.services.update_service import oss_service
    from app.core.config import get_settings
    settings = get_settings()

    output: list[ChapterItem] = []

    for chapter in chapters:
        row = progress_map.get(str(chapter.id))
        if row and row.status in ("IN_PROGRESS", "COMPLETED"):
            status = row.status
        else:
            status = "NOT_STARTED"

        release = bundle_by_chapter.get(str(chapter.id))
        bundle_url = None
        if release:
            bundle_url = oss_service.resolve_download_url(
                release.artifact_url,
                expires_seconds=settings.oss_download_url_expire_seconds,
            )

        output.append(
            ChapterItem(
                id=str(chapter.id),
                chapter_code=chapter.chapter_code,
                title=chapter.title,
                intro_text=chapter.intro_text,
                status=status,
                locked=False,
                order=chapter.sort_order,
                bundle_url=bundle_url,
                bundle_version=release.version if release else None,
                bundle_sha256=release.sha256 if release else None,
                bundle_size_bytes=release.size_bytes if release else None,
            )
        )

    return CourseChaptersResponse(course_id=course_id, chapters=output)
