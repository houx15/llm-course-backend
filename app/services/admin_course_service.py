from __future__ import annotations

import secrets
import string

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.models import BundleRelease, ChapterProgress, Course, CourseChapter, Enrollment
from app.schemas.admin_courses import AdminChapterCreate, AdminChapterUpsertRequest, AdminCourseCreateRequest


def _generate_invite_code(db: Session, length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = "".join(secrets.choice(chars) for _ in range(length))
        exists = db.execute(select(Course.id).where(Course.invite_code == code)).scalar_one_or_none()
        if not exists:
            return code
    raise RuntimeError("Failed to generate unique invite code")


def create_course_with_chapters(db: Session, payload: AdminCourseCreateRequest) -> Course:
    try:
        invite_code = _generate_invite_code(db)
        course = Course(
            course_code=invite_code,
            title=payload.title.strip(),
            description=payload.description.strip(),
            instructor=payload.instructor.strip(),
            semester=payload.semester.strip(),
            overview_experience=payload.overview_experience.strip(),
            overview_gains=payload.overview_gains.strip(),
            overview_necessity=payload.overview_necessity.strip(),
            overview_journey=payload.overview_journey.strip(),
            invite_code=invite_code,
            is_active=payload.is_active,
            is_public=payload.is_public,
        )
        db.add(course)
        db.flush()

        for chapter in payload.chapters:
            db.add(_chapter_from_input(course.id, chapter))

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(status_code=409, code="COURSE_OR_CHAPTER_CONFLICT", message="Course or chapter already exists") from exc

    db.refresh(course)
    return course


def _chapter_from_input(course_id, chapter: AdminChapterCreate) -> CourseChapter:
    return CourseChapter(
        course_id=course_id,
        chapter_code=chapter.chapter_code.strip(),
        title=chapter.title.strip(),
        intro_text=chapter.intro_text.strip(),
        sort_order=chapter.order,
        is_active=chapter.is_active,
    )


def get_course_or_404(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise ApiError(status_code=404, code=ErrorCode.COURSE_NOT_FOUND, message="Course not found")
    return course


def update_course(db: Session, course_id: str, payload) -> Course:
    course = get_course_or_404(db, course_id)
    for field in [
        "title", "description", "instructor", "semester", "is_active", "is_public",
        "overview_experience", "overview_gains", "overview_necessity", "overview_journey",
    ]:
        value = getattr(payload, field, None)
        if value is not None:
            setattr(course, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(course)
    return course


def list_course_chapters_with_bundle_flag(db: Session, course_id: str) -> list[tuple[CourseChapter, bool]]:
    chapters = db.execute(
        select(CourseChapter).where(CourseChapter.course_id == course_id).order_by(CourseChapter.sort_order.asc())
    ).scalars().all()
    if not chapters:
        return []

    # Use chapter UUID as scope_id for bundle lookup
    scopes = [str(chapter.id) for chapter in chapters]
    available_scopes = set(
        db.execute(
            select(BundleRelease.scope_id).where(
                BundleRelease.bundle_type == "chapter",
                BundleRelease.scope_id.in_(scopes),
            )
        ).scalars().all()
    )
    return [(chapter, str(chapter.id) in available_scopes) for chapter in chapters]


def has_chapter_bundle(db: Session, *, chapter_id: str) -> bool:
    """Check if a chapter bundle exists using chapter UUID as scope."""
    exists = db.execute(
        select(BundleRelease.id).where(BundleRelease.bundle_type == "chapter", BundleRelease.scope_id == chapter_id).limit(1)
    ).scalar_one_or_none()
    return exists is not None


def upsert_course_chapter(
    db: Session,
    *,
    course_id: str,
    chapter_code: str,
    payload: AdminChapterUpsertRequest,
) -> CourseChapter:
    existing = db.execute(
        select(CourseChapter).where(CourseChapter.course_id == course_id, CourseChapter.chapter_code == chapter_code)
    ).scalars().first()
    if existing:
        existing.title = payload.title.strip()
        existing.intro_text = payload.intro_text.strip()
        existing.sort_order = payload.order
        existing.is_active = payload.is_active
        db.commit()
        db.refresh(existing)
        return existing

    chapter = CourseChapter(
        course_id=course_id,
        chapter_code=chapter_code.strip(),
        title=payload.title.strip(),
        intro_text=payload.intro_text.strip(),
        sort_order=payload.order,
        is_active=payload.is_active,
    )
    db.add(chapter)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(status_code=409, code="CHAPTER_CONFLICT", message="Chapter already exists") from exc
    db.refresh(chapter)
    return chapter


def update_chapter_intro(
    db: Session,
    *,
    course_id: str,
    chapter_code: str,
    intro_text: str,
) -> CourseChapter:
    chapter = db.execute(
        select(CourseChapter).where(CourseChapter.course_id == course_id, CourseChapter.chapter_code == chapter_code)
    ).scalars().first()
    if not chapter:
        raise ApiError(status_code=404, code=ErrorCode.CHAPTER_NOT_FOUND, message="Chapter not found")
    chapter.intro_text = intro_text.strip()
    db.commit()
    db.refresh(chapter)
    return chapter


def list_all_courses(db: Session) -> list[tuple[Course, int]]:
    """Return all courses (newest first) paired with their chapter count."""
    courses = db.execute(select(Course).order_by(Course.created_at.desc())).scalars().all()
    if not courses:
        return []
    course_ids = [c.id for c in courses]
    counts_result = db.execute(
        select(CourseChapter.course_id, func.count(CourseChapter.id).label("cnt"))
        .where(CourseChapter.course_id.in_(course_ids))
        .group_by(CourseChapter.course_id)
    ).all()
    count_map = {row.course_id: row.cnt for row in counts_result}
    return [(course, count_map.get(course.id, 0)) for course in courses]


def delete_course(db: Session, course_id: str, *, delete_bundles: bool = False) -> None:
    """Hard-delete a course, its chapters, enrollments, and chapter progress.

    If delete_bundles=True also removes the associated chapter BundleReleases.
    """
    course = get_course_or_404(db, course_id)

    if delete_bundles:
        # Use chapter UUID as scope_id for bundle lookup
        chapter_ids = db.execute(
            select(CourseChapter.id).where(CourseChapter.course_id == course.id)
        ).scalars().all()
        scopes = [str(cid) for cid in chapter_ids]
        if scopes:
            db.execute(
                sql_delete(BundleRelease).where(
                    BundleRelease.bundle_type == "chapter",
                    BundleRelease.scope_id.in_(scopes),
                )
            )

    db.execute(sql_delete(ChapterProgress).where(ChapterProgress.course_id == course.id))
    db.execute(sql_delete(Enrollment).where(Enrollment.course_id == course.id))
    db.execute(sql_delete(CourseChapter).where(CourseChapter.course_id == course.id))
    db.delete(course)
    db.commit()


def delete_chapter(db: Session, *, course_id: str, chapter_code: str, delete_bundles: bool = False) -> None:
    """Soft-delete a chapter by setting is_active=False.

    If delete_bundles=True also removes the chapter's BundleReleases.
    """
    get_course_or_404(db, course_id)
    chapter = db.execute(
        select(CourseChapter).where(
            CourseChapter.course_id == course_id,
            CourseChapter.chapter_code == chapter_code,
        )
    ).scalars().first()
    if not chapter:
        raise ApiError(status_code=404, code=ErrorCode.CHAPTER_NOT_FOUND, message="Chapter not found")

    if delete_bundles:
        scope = str(chapter.id)
        db.execute(
            sql_delete(BundleRelease).where(
                BundleRelease.bundle_type == "chapter",
                BundleRelease.scope_id == scope,
            )
        )

    chapter.is_active = False
    db.commit()
