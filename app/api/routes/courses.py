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
    code = payload.course_code.strip().upper()
    course = db.execute(select(Course).where(Course.course_code == code, Course.is_active.is_(True))).scalars().first()
    if not course:
        raise ApiError(status_code=404, code=ErrorCode.COURSE_NOT_FOUND, message="Course not found")

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

    return CourseDetailResponse(id=str(course.id), title=course.title, description=course.description, instructor=course.instructor)


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
    course_obj = db.get(Course, course_id)
    course_code = course_obj.course_code if course_obj else course_id
    scope_to_chapter = {f"{course_code}/{chapter.chapter_code}": chapter for chapter in chapters_all}
    if not scope_to_chapter:
        return CourseChaptersResponse(course_id=course_id, chapters=[])

    available_scopes = set(
        db.execute(
            select(BundleRelease.scope_id).where(
                BundleRelease.bundle_type == "chapter",
                BundleRelease.scope_id.in_(list(scope_to_chapter.keys())),
            )
        ).scalars().all()
    )
    chapters = [scope_to_chapter[scope] for scope in scope_to_chapter if scope in available_scopes]

    progress_rows = db.execute(
        select(ChapterProgress).where(ChapterProgress.user_id == current_user.id, ChapterProgress.course_id == course_id)
    ).scalars().all()
    progress_map = {str(row.chapter_id): row for row in progress_rows}

    output: list[ChapterItem] = []
    prev_completed = True

    for idx, chapter in enumerate(chapters):
        row = progress_map.get(str(chapter.id))
        if row:
            status = row.status
            locked = status == "LOCKED"
        else:
            locked = idx > 0 and not prev_completed
            status = "LOCKED" if locked else "IN_PROGRESS"

        output.append(
            ChapterItem(
                id=chapter.chapter_code,
                chapter_code=chapter.chapter_code,
                title=chapter.title,
                intro_text=chapter.intro_text,
                status=status,
                locked=locked,
                order=chapter.sort_order,
            )
        )

        prev_completed = status == "COMPLETED"

    return CourseChaptersResponse(course_id=course_id, chapters=output)
