from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, CourseChapter


def seed_if_needed(db: Session) -> None:
    existing_course = db.execute(select(Course).where(Course.course_code == "SOC101")).scalars().first()
    if existing_course:
        return

    course = Course(
        course_code="SOC101",
        title="LLM and Social Science",
        description="Socratic guided course for social science workflows with LLMs.",
        instructor="Prof. AI",
        semester="Spring 2026",
        is_active=True,
    )
    db.add(course)
    db.flush()

    ch1 = CourseChapter(
        course_id=course.id,
        chapter_code="ch1_intro",
        title="Introduction",
        intro_text="Foundational concepts and workflow overview.",
        sort_order=1,
        is_active=True,
    )
    ch2 = CourseChapter(
        course_id=course.id,
        chapter_code="ch2_pandas",
        title="Pandas Basics",
        intro_text="Core data operations for social-science datasets.",
        sort_order=2,
        is_active=True,
    )
    db.add_all([ch1, ch2])
    db.commit()
    # BundleRelease records are NOT seeded here — use upload_bundle.py to register
    # real bundles with actual OSS URLs. Seeding fake cdn.example.com URLs causes
    # ENOTFOUND errors in the desktop when it tries to download them.
