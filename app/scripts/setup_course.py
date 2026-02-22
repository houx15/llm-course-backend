#!/usr/bin/env python3
"""
Create or sync a course (with chapters) directly from the curriculum directory.

Reads course_overview.json and all chapters/*/chapter.json files — those JSON
files are the single source of truth. No intermediate YAML config needed.

Usage:
    # Create or sync a course (idempotent):
    uv run python app/scripts/setup_course.py \\
        --course-dir /path/to/demo/curriculum/courses/course2_political_data_analysis \\
        --course-code SOC201

    # Dry-run (print what would happen):
    uv run python app/scripts/setup_course.py \\
        --course-dir /path/to/demo/curriculum/courses/course2_political_data_analysis \\
        --course-code SOC201 --dry-run

Expected directory layout:
    course_dir/
    ├── course_overview.json          # course title + overview text
    └── chapters/
        ├── ch1_first_contact/
        │   └── chapter.json          # chapter metadata (title, sort_order, intro_text, ...)
        └── ch2_python_basis/
            └── chapter.json

course_overview.json format:
    {
      "title": "政治数据分析",
      "overview": {
        "experience": "...",
        "gains": "...",
        "necessity": "...",
        "journey": "..."
      }
    }

chapter.json format:
    {
      "chapter_code": "ch2_python_basis_pandas_fundamental",
      "title": "Python数据类型与pandas基础操作",
      "sort_order": 2,
      "intro_text": "...",
      "available_experts": ["data_inspector", "concept_explainer"]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Course, CourseChapter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync a course to the database from curriculum JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--course-dir", required=True, type=Path, help="Path to course directory")
    parser.add_argument("--course-code", required=True, help="Course code, e.g. SOC201")
    parser.add_argument("--instructor", default="AI Tutor", help="Instructor name (default: AI Tutor)")
    parser.add_argument("--semester", default="", help="Semester label, e.g. Spring 2025")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing to DB")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def discover_chapters(course_dir: Path) -> list[dict[str, Any]]:
    chapters_dir = course_dir / "chapters"
    if not chapters_dir.is_dir():
        return []

    chapters: list[dict[str, Any]] = []
    for chapter_json in sorted(chapters_dir.glob("*/chapter.json")):
        data = load_json(chapter_json)
        data["_dir"] = chapter_json.parent
        chapters.append(data)

    # Sort by sort_order, then by directory name as fallback
    chapters.sort(key=lambda c: (c.get("sort_order") or 999, c["_dir"].name))
    return chapters


def main() -> int:
    args = parse_args()
    course_dir = args.course_dir.resolve()

    if not course_dir.is_dir():
        print(f"Error: course directory not found: {course_dir}", file=sys.stderr)
        return 1

    # Load course overview
    overview_path = course_dir / "course_overview.json"
    if not overview_path.exists():
        print(f"Error: course_overview.json not found in {course_dir}", file=sys.stderr)
        return 1

    overview = load_json(overview_path)
    course_title = overview.get("title") or course_dir.name
    description = overview.get("description", "")
    course_code = args.course_code.strip().upper()

    # Discover chapters
    chapters = discover_chapters(course_dir)
    if not chapters:
        print("Warning: no chapter.json files found under chapters/*/chapter.json")

    print(f"Course : {course_code} — {course_title}")
    print(f"Chapters discovered: {len(chapters)}")
    for ch in chapters:
        print(f"  [{ch.get('sort_order', '?')}] {ch.get('chapter_code', '?')} — {ch.get('title', '?')}")

    if args.dry_run:
        print("\n[dry-run] No changes made.")
        return 0

    with SessionLocal() as db:
        # Upsert course
        course = db.execute(select(Course).where(Course.course_code == course_code)).scalars().first()
        if not course:
            course = Course(
                course_code=course_code,
                title=course_title,
                description=description,
                instructor=args.instructor,
                semester=args.semester,
                is_active=True,
            )
            db.add(course)
            db.flush()
            print(f"\nCreated course id={course.id}")
        else:
            course.title = course_title
            course.description = description
            if args.instructor:
                course.instructor = args.instructor
            if args.semester:
                course.semester = args.semester
            db.add(course)
            print(f"\nUpdating course id={course.id}")

        # Upsert chapters
        created = updated = 0
        for ch in chapters:
            chapter_code = (ch.get("chapter_code") or ch["_dir"].name).strip()
            ch_title = (ch.get("title") or chapter_code).strip()
            intro_text = (ch.get("intro_text") or "").strip()
            sort_order = int(ch.get("sort_order") or 0)

            existing = db.execute(
                select(CourseChapter).where(
                    CourseChapter.course_id == course.id,
                    CourseChapter.chapter_code == chapter_code,
                )
            ).scalars().first()

            if existing:
                existing.title = ch_title
                existing.intro_text = intro_text
                existing.sort_order = sort_order
                db.add(existing)
                updated += 1
            else:
                db.add(CourseChapter(
                    course_id=course.id,
                    chapter_code=chapter_code,
                    title=ch_title,
                    intro_text=intro_text,
                    sort_order=sort_order,
                    is_active=True,
                ))
                created += 1

        db.commit()

    print(f"Chapters created: {created}, updated: {updated}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
