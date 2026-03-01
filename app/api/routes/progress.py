from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.core.security import now_utc
from app.db.session import get_db
from app.models import ChapterProgress, Course, CourseChapter, Enrollment
from app.schemas.progress import ChapterProgressRequest, ChapterProgressResponse

router = APIRouter(prefix="/v1/progress", tags=["progress"])


@router.post("/chapter", response_model=ChapterProgressResponse)
def upsert_chapter_progress(
    payload: ChapterProgressRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> ChapterProgressResponse:
    course = db.get(Course, payload.course_id)
    if not course:
        raise ApiError(status_code=404, code=ErrorCode.COURSE_NOT_FOUND, message="Course not found")

    enrollment = db.execute(
        select(Enrollment).where(
            Enrollment.user_id == current_user.id,
            Enrollment.course_id == course.id,
            Enrollment.status == "active",
        )
    ).scalars().first()
    if not enrollment:
        raise ApiError(status_code=403, code=ErrorCode.COURSE_ACCESS_DENIED, message="Course not enrolled")

    # Try UUID lookup first (desktop sends UUID as chapter_id), fall back to chapter_code
    chapter = None
    try:
        chapter = db.get(CourseChapter, payload.chapter_id)
    except Exception:
        pass
    if not chapter or str(chapter.course_id) != str(course.id):
        chapter = db.execute(
            select(CourseChapter).where(
                CourseChapter.course_id == course.id,
                CourseChapter.chapter_code == payload.chapter_id,
            )
        ).scalars().first()
    if not chapter:
        raise ApiError(status_code=404, code=ErrorCode.CHAPTER_NOT_FOUND, message="Chapter not found")

    row = db.execute(
        select(ChapterProgress).where(
            ChapterProgress.user_id == current_user.id,
            ChapterProgress.course_id == course.id,
            ChapterProgress.chapter_id == chapter.id,
        )
    ).scalars().first()

    if not row:
        row = ChapterProgress(
            user_id=current_user.id,
            course_id=course.id,
            chapter_id=chapter.id,
            status=payload.status,
            last_session_id=payload.session_id,
            task_snapshot=payload.task_snapshot,
        )
    else:
        row.status = payload.status
        row.last_session_id = payload.session_id
        row.task_snapshot = payload.task_snapshot

    db.add(row)
    db.commit()

    return ChapterProgressResponse(accepted=True, server_time=now_utc())
