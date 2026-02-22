#!/usr/bin/env python3
"""
Reset all course, chapter, enrollment, progress, and chapter bundle data.

Keeps: Users, DeviceSessions, auth data, app/experts/python_runtime bundles.
Use --dry-run to preview what would be deleted without making changes.

Usage:
    uv run python app/scripts/reset_courses.py
    uv run python app/scripts/reset_courses.py --dry-run
    uv run python app/scripts/reset_courses.py --all-bundles   # also wipe experts/agents/runtime bundles
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from sqlalchemy import func, select, text

from app.db.session import SessionLocal
from app.models import BundleRelease, ChapterProgress, Course, CourseChapter, Enrollment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wipe all course/chapter/enrollment/bundle data from the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would be deleted without making changes")
    parser.add_argument(
        "--all-bundles",
        action="store_true",
        help="Also delete app_agents, experts, experts_shared, python_runtime bundles (default: chapter only)",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    with SessionLocal() as db:
        # Count rows that will be deleted
        n_progress = db.execute(select(func.count()).select_from(ChapterProgress)).scalar_one()
        n_enrollments = db.execute(select(func.count()).select_from(Enrollment)).scalar_one()
        n_chapters = db.execute(select(func.count()).select_from(CourseChapter)).scalar_one()
        n_courses = db.execute(select(func.count()).select_from(Course)).scalar_one()

        if args.all_bundles:
            n_bundles = db.execute(select(func.count()).select_from(BundleRelease)).scalar_one()
            bundle_label = "ALL bundle_releases"
        else:
            n_bundles = db.execute(
                select(func.count()).select_from(BundleRelease).where(BundleRelease.bundle_type == "chapter")
            ).scalar_one()
            bundle_label = "chapter bundle_releases"

        print("Would delete:" if args.dry_run else "Will delete:")
        print(f"  chapter_progress : {n_progress:>6} rows")
        print(f"  enrollments      : {n_enrollments:>6} rows")
        print(f"  course_chapters  : {n_chapters:>6} rows")
        print(f"  courses          : {n_courses:>6} rows")
        print(f"  {bundle_label:<17}: {n_bundles:>6} rows")

        if args.dry_run:
            print("\n[dry-run] No changes made.")
            return 0

        if not args.yes:
            try:
                answer = input("\nProceed? [yes/no]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                return 1
            if answer != "yes":
                print("Aborted.")
                return 1

        # Delete in FK-dependency order
        deleted = {}
        deleted["chapter_progress"] = db.query(ChapterProgress).delete(synchronize_session=False)
        deleted["enrollments"] = db.query(Enrollment).delete(synchronize_session=False)
        deleted["course_chapters"] = db.query(CourseChapter).delete(synchronize_session=False)
        deleted["courses"] = db.query(Course).delete(synchronize_session=False)

        if args.all_bundles:
            deleted["bundle_releases"] = db.query(BundleRelease).delete(synchronize_session=False)
        else:
            deleted["bundle_releases (chapter)"] = (
                db.query(BundleRelease).filter(BundleRelease.bundle_type == "chapter").delete(synchronize_session=False)
            )

        db.commit()

    print("\nDeleted:")
    for label, count in deleted.items():
        print(f"  {label:<30}: {count} rows")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
