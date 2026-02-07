from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BundleRelease, Course, CourseChapter


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

    ch1 = CourseChapter(course_id=course.id, chapter_code="ch1_intro", title="Introduction", sort_order=1, is_active=True)
    ch2 = CourseChapter(course_id=course.id, chapter_code="ch2_pandas", title="Pandas Basics", sort_order=2, is_active=True)
    db.add_all([ch1, ch2])

    db.add_all(
        [
            BundleRelease(
                bundle_type="app_agents",
                scope_id="core",
                version="1.0.0",
                manifest_json={"min_desktop_version": "0.1.0", "min_sidecar_version": "0.1.0"},
                artifact_url="https://cdn.example.com/bundles/app_agents/core/1.0.0/bundle.tar.gz",
                sha256="abc123",
                size_bytes=128000,
                is_mandatory=True,
            ),
            BundleRelease(
                bundle_type="experts_shared",
                scope_id="shared",
                version="1.0.0",
                manifest_json={},
                artifact_url="https://cdn.example.com/bundles/experts_shared/shared/1.0.0/bundle.tar.gz",
                sha256="ghi789",
                size_bytes=88000,
                is_mandatory=False,
            ),
            BundleRelease(
                bundle_type="chapter",
                scope_id=f"{course.id}/ch1_intro",
                version="1.0.0",
                manifest_json={"required_experts": ["data_inspector", "concept_explainer"]},
                artifact_url=f"https://cdn.example.com/bundles/chapter/{course.id}/ch1_intro/1.0.0/bundle.tar.gz",
                sha256="def456",
                size_bytes=220000,
                is_mandatory=True,
            ),
            BundleRelease(
                bundle_type="experts",
                scope_id="data_inspector",
                version="1.0.0",
                manifest_json={},
                artifact_url="https://cdn.example.com/bundles/experts/data_inspector/1.0.0/bundle.tar.gz",
                sha256="exp111",
                size_bytes=64000,
                is_mandatory=False,
            ),
            BundleRelease(
                bundle_type="experts",
                scope_id="concept_explainer",
                version="1.0.0",
                manifest_json={},
                artifact_url="https://cdn.example.com/bundles/experts/concept_explainer/1.0.0/bundle.tar.gz",
                sha256="exp222",
                size_bytes=61000,
                is_mandatory=False,
            ),
        ]
    )

    db.commit()
