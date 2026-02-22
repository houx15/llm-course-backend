#!/usr/bin/env python3
"""
Create or sync a course (with chapters) via the admin REST API.

Reads course_overview.json and all chapters/*/chapter.json files and
calls POST /v1/admin/courses (create) or PUT /v1/admin/courses/{id}/chapters/{code}
(upsert each chapter) so it works against the remote server without a direct DB
connection.

Usage:
    uv run python app/scripts/setup_course.py \\
        --course-dir /path/to/demo/curriculum/courses/course2_political_data_analysis \\
        --course-code SOC201 \\
        --server http://47.93.151.131:10723 \\
        --admin-key YOUR_KEY

    # Dry-run (print what would happen):
    uv run python app/scripts/setup_course.py \\
        --course-dir /path/to/demo/curriculum/courses/course2_political_data_analysis \\
        --course-code SOC201 \\
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
    parser.add_argument("--course-code", required=True, help="Course code, e.g. SOC201")
    parser.add_argument("--server", required=True, help="Backend URL, e.g. http://47.93.151.131:10723")
    parser.add_argument("--admin-key", required=True, help="Admin API key")
    parser.add_argument("--instructor", default="AI Tutor", help="Instructor name (default: AI Tutor)")
    parser.add_argument("--semester", default="", help="Semester label, e.g. Spring 2025")
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
    course_code = args.course_code.strip().upper()
    chapters = discover_chapters(course_dir)

    print(f"Course : {course_code} — {course_title}")
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
        "course_code": course_code,
        "title": course_title,
        "description": description,
        "instructor": args.instructor,
        "semester": args.semester,
        "is_active": True,
        "chapters": chapter_payloads,
    }

    with httpx.Client(timeout=30.0) as client:
        # Try creating the course
        resp = client.post(f"{server}/v1/admin/courses", json=course_payload, headers=headers)

        if resp.status_code == 201:
            result = resp.json()
            print(f"\nCreated course id={result['id']}")
            print(f"  chapters: {len(result.get('chapters', []))}")
            print("Done.")
            return 0

        if resp.status_code == 409:
            # Course already exists — fetch it, then upsert each chapter
            print("\nCourse already exists, fetching to upsert chapters...")
            list_resp = client.get(f"{server}/v1/admin/courses", headers=headers)
            if list_resp.status_code != 200:
                print(f"Error fetching courses: HTTP {list_resp.status_code}: {list_resp.text[:200]}", file=sys.stderr)
                return 1

            course_id = None
            for c in list_resp.json().get("courses", []):
                if c["course_code"] == course_code:
                    course_id = c["id"]
                    break

            if not course_id:
                print(f"Error: course {course_code} not found after 409", file=sys.stderr)
                return 1

            print(f"Found course id={course_id}")
            ok = 0
            for ch in chapter_payloads:
                ch_resp = client.put(
                    f"{server}/v1/admin/courses/{course_id}/chapters/{ch['chapter_code']}",
                    json=ch,
                    headers=headers,
                )
                if ch_resp.status_code in (200, 201):
                    print(f"  upserted: {ch['chapter_code']}")
                    ok += 1
                else:
                    print(f"  FAILED {ch['chapter_code']}: HTTP {ch_resp.status_code} {ch_resp.text[:100]}", file=sys.stderr)

            print(f"\nUpserted {ok}/{len(chapter_payloads)} chapters.")
            print("Done.")
            return 0 if ok == len(chapter_payloads) else 1

        print(f"Error creating course: HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
