from __future__ import annotations

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.models import BundleRelease, ChapterProgress, Course, CourseChapter, Enrollment
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
        chapter_codes = db.execute(
            select(CourseChapter.chapter_code).where(CourseChapter.course_id == course.id)
        ).scalars().all()
        scopes = [f"{course_id}/{code}" for code in chapter_codes]
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
    """Hard-delete a single chapter (and its progress records).

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
        scope = f"{course_id}/{chapter_code}"
        db.execute(
            sql_delete(BundleRelease).where(
                BundleRelease.bundle_type == "chapter",
                BundleRelease.scope_id == scope,
            )
        )

    db.execute(sql_delete(ChapterProgress).where(ChapterProgress.chapter_id == chapter.id))
    db.delete(chapter)
    db.commit()
