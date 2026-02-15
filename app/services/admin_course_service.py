from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.models import BundleRelease, Course, CourseChapter
from app.schemas.admin_courses import AdminChapterCreate, AdminChapterUpsertRequest, AdminCourseCreateRequest


def create_course_with_chapters(db: Session, payload: AdminCourseCreateRequest) -> Course:
    try:
        course = Course(
            course_code=payload.course_code.strip().upper(),
            title=payload.title.strip(),
            description=payload.description.strip(),
            instructor=payload.instructor.strip(),
            semester=payload.semester.strip(),
            is_active=payload.is_active,
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


def list_course_chapters_with_bundle_flag(db: Session, course_id: str) -> list[tuple[CourseChapter, bool]]:
    chapters = db.execute(
        select(CourseChapter).where(CourseChapter.course_id == course_id).order_by(CourseChapter.sort_order.asc())
    ).scalars().all()
    if not chapters:
        return []

    scopes = [f"{course_id}/{chapter.chapter_code}" for chapter in chapters]
    available_scopes = set(
        db.execute(
            select(BundleRelease.scope_id).where(
                BundleRelease.bundle_type == "chapter",
                BundleRelease.scope_id.in_(scopes),
            )
        ).scalars().all()
    )
    return [(chapter, f"{course_id}/{chapter.chapter_code}" in available_scopes) for chapter in chapters]


def has_chapter_bundle(db: Session, *, course_id: str, chapter_code: str) -> bool:
    scope = f"{course_id}/{chapter_code}"
    exists = db.execute(
        select(BundleRelease.id).where(BundleRelease.bundle_type == "chapter", BundleRelease.scope_id == scope).limit(1)
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
