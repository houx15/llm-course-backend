#!/usr/bin/env python3
"""
Create or sync a course (with chapters) via the admin REST API.

Reads course_overview.json and all chapters/*/chapter.json files and
calls POST /v1/admin/courses (create) or PUT /v1/admin/courses/{id}/chapters/{code}
(upsert each chapter) so it works against the remote server without a direct DB
connection.

Usage:
    uv run python app/scripts/setup_course.py \\
        --course-dir /path/to/bundles/curriculum/courses/course1 \\
        --server http://47.93.151.131:10723 \\
        --admin-key YOUR_KEY

    # Dry-run (print what would happen):
    uv run python app/scripts/setup_course.py \\
        --course-dir /path/to/bundles/curriculum/courses/course1 \\
        --server http://47.93.151.131:10723 \\
        --admin-key YOUR_KEY --dry-run

Expected directory layout:
    course_dir/
    ├── course_overview.json          # course title + overview text
    └── chapters/
        ├── ch1_first_contact/
        │   └── chapter.json          # chapter metadata
        └── ch2_python_basis/
            └── chapter.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync a course to the database via admin API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--course-dir", required=True, type=Path, help="Path to course directory")
    parser.add_argument("--server", required=True, help="Backend URL, e.g. http://47.93.151.131:10723")
    parser.add_argument("--admin-key", required=True, help="Admin API key")
    parser.add_argument("--instructor", default=None, help="Instructor name (overrides course_overview.json)")
    parser.add_argument("--semester", default=None, help="Semester label (overrides course_overview.json)")
    parser.add_argument("--public", action="store_true", default=None, help="Mark course as public (overrides course_overview.json)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without calling the API")
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
    chapters.sort(key=lambda c: (c.get("sort_order") or 999, c["_dir"].name))
    return chapters


def main() -> int:
    args = parse_args()
    course_dir = args.course_dir.resolve()

    if not course_dir.is_dir():
        print(f"Error: course directory not found: {course_dir}", file=sys.stderr)
        return 1

    overview_path = course_dir / "course_overview.json"
    if not overview_path.exists():
        print(f"Error: course_overview.json not found in {course_dir}", file=sys.stderr)
        return 1

    overview = load_json(overview_path)
    course_title = overview.get("title") or course_dir.name
    description = overview.get("description", "")
    instructor = args.instructor or overview.get("instructor", "") or "AI Tutor"
    semester = args.semester if args.semester is not None else overview.get("semester", "")
    is_public = args.public if args.public is not None else overview.get("is_public", False)
    chapters = discover_chapters(course_dir)

    print(f"Course : {course_title}")
    print(f"Chapters discovered: {len(chapters)}")
    for ch in chapters:
        print(f"  [{ch.get('sort_order', '?')}] {ch.get('chapter_code', '?')} — {ch.get('title', '?')}")

    if args.dry_run:
        print("\n[dry-run] No changes made.")
        return 0

    server = args.server.rstrip("/")
    headers = {"X-Admin-Key": args.admin_key}

    chapter_payloads = [
        {
            "chapter_code": (ch.get("chapter_code") or ch["_dir"].name).strip(),
            "title": (ch.get("title") or ch["_dir"].name).strip(),
            "order": int(ch.get("sort_order") or 0),
            "intro_text": (ch.get("intro_text") or "").strip(),
            "is_active": True,
        }
        for ch in chapters
    ]

    course_payload = {
        "title": course_title,
        "description": description,
        "instructor": instructor,
        "semester": semester,
        "overview_experience": overview.get("overview", {}).get("experience", ""),
        "overview_gains": overview.get("overview", {}).get("gains", ""),
        "overview_necessity": overview.get("overview", {}).get("necessity", ""),
        "overview_journey": overview.get("overview", {}).get("journey", ""),
        "is_active": True,
        "is_public": is_public,
        "chapters": chapter_payloads,
    }

    with httpx.Client(timeout=30.0) as client:
        # Try creating the course
        resp = client.post(f"{server}/v1/admin/courses", json=course_payload, headers=headers)

        if resp.status_code == 201:
            result = resp.json()
            print(f"\nCreated course id={result['id']}")
            print(f"  Invite Code: {result.get('invite_code', 'N/A')}")
            print(f"  Chapters ({len(result.get('chapters', []))}):")
            for ch in result.get("chapters", []):
                print(f"    {ch['chapter_code']} -> UUID: {ch['id']}")
            print("Done.")
            return 0

        print(f"Error creating course: HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
