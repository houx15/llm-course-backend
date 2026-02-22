from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.admin_auth import require_admin_key
from app.db.session import get_db
from app.models import Course, CourseChapter
from app.schemas.admin_courses import (
    AdminChapterIntroUpdateRequest,
    AdminChapterResponse,
    AdminChapterUpsertRequest,
    AdminCourseCreateRequest,
    AdminCourseListResponse,
    AdminCourseResponse,
    AdminCourseSummaryResponse,
    AdminCourseWithChaptersResponse,
)
from app.services.admin_course_service import (
    create_course_with_chapters,
    delete_chapter,
    delete_course,
    get_course_or_404,
    has_chapter_bundle,
    list_all_courses,
    list_course_chapters_with_bundle_flag,
    update_chapter_intro,
    upsert_course_chapter,
)

router = APIRouter(prefix="/v1/admin/courses", tags=["admin"], dependencies=[Depends(require_admin_key)])


def _course_response(course: Course) -> AdminCourseResponse:
    return AdminCourseResponse(
        id=str(course.id),
        course_code=course.course_code,
        title=course.title,
        description=course.description,
        instructor=course.instructor,
        semester=course.semester,
        is_active=course.is_active,
        created_at=course.created_at.isoformat(),
    )


def _chapter_response(chapter: CourseChapter, *, has_bundle: bool) -> AdminChapterResponse:
    return AdminChapterResponse(
        id=str(chapter.id),
        chapter_code=chapter.chapter_code,
        title=chapter.title,
        intro_text=chapter.intro_text,
        order=chapter.sort_order,
        is_active=chapter.is_active,
        has_bundle=has_bundle,
        created_at=chapter.created_at.isoformat(),
    )


@router.get("", response_model=AdminCourseListResponse)
def list_courses(
    db: Session = Depends(get_db),
) -> AdminCourseListResponse:
    courses_with_counts = list_all_courses(db)
    items = [
        AdminCourseSummaryResponse(**_course_response(course).model_dump(), chapter_count=count)
        for course, count in courses_with_counts
    ]
    return AdminCourseListResponse(courses=items, total=len(items))


@router.post("", response_model=AdminCourseWithChaptersResponse, status_code=201)
def create_course(
    payload: AdminCourseCreateRequest,
    db: Session = Depends(get_db),
) -> AdminCourseWithChaptersResponse:
    course = create_course_with_chapters(db, payload)
    chapters = list_course_chapters_with_bundle_flag(db, str(course.id))
    return AdminCourseWithChaptersResponse(
        **_course_response(course).model_dump(),
        chapters=[_chapter_response(chapter, has_bundle=has_bundle) for chapter, has_bundle in chapters],
    )


@router.get("/{course_id}", response_model=AdminCourseWithChaptersResponse)
def get_course(
    course_id: str,
    db: Session = Depends(get_db),
) -> AdminCourseWithChaptersResponse:
    course = get_course_or_404(db, course_id)
    chapters = list_course_chapters_with_bundle_flag(db, course_id)
    return AdminCourseWithChaptersResponse(
        **_course_response(course).model_dump(),
        chapters=[_chapter_response(chapter, has_bundle=has_bundle) for chapter, has_bundle in chapters],
    )


@router.put("/{course_id}/chapters/{chapter_code}", response_model=AdminChapterResponse)
def upsert_chapter(
    course_id: str,
    chapter_code: str,
    payload: AdminChapterUpsertRequest,
    db: Session = Depends(get_db),
) -> AdminChapterResponse:
    get_course_or_404(db, course_id)
    chapter = upsert_course_chapter(db, course_id=course_id, chapter_code=chapter_code, payload=payload)
    return _chapter_response(chapter, has_bundle=has_chapter_bundle(db, course_id=course_id, chapter_code=chapter.chapter_code))


@router.patch("/{course_id}/chapters/{chapter_code}/intro", response_model=AdminChapterResponse)
def patch_chapter_intro(
    course_id: str,
    chapter_code: str,
    payload: AdminChapterIntroUpdateRequest,
    db: Session = Depends(get_db),
) -> AdminChapterResponse:
    chapter = update_chapter_intro(db, course_id=course_id, chapter_code=chapter_code, intro_text=payload.intro_text)
    return _chapter_response(chapter, has_bundle=has_chapter_bundle(db, course_id=course_id, chapter_code=chapter.chapter_code))


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course_endpoint(
    course_id: str,
    delete_bundles: bool = Query(default=False, description="Also delete associated chapter bundle releases"),
    db: Session = Depends(get_db),
) -> Response:
    delete_course(db, course_id, delete_bundles=delete_bundles)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{course_id}/chapters/{chapter_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chapter_endpoint(
    course_id: str,
    chapter_code: str,
    delete_bundles: bool = Query(default=False, description="Also delete the chapter's bundle releases"),
    db: Session = Depends(get_db),
) -> Response:
    delete_chapter(db, course_id=course_id, chapter_code=chapter_code, delete_bundles=delete_bundles)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
