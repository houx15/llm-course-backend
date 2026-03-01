"""Create users from CSV and enroll them in public courses + specified courses.

CSV format (header required):
    username,display_name,invite_codes
    pangxun,庞珣,
    tangshiyun,唐诗韵,ABC123;DEF456

- invite_codes: semicolon-separated invite codes (optional)
- All users are auto-enrolled in public active courses
- If invite_codes are provided, also enrolled in those courses

Usage:
    uv run python app/scripts/create_batch_users.py --csv users.csv
    uv run python app/scripts/create_batch_users.py --csv users.csv --domain example.com
    uv run python app/scripts/create_batch_users.py --csv users.csv --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Course, Enrollment, User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create users from CSV and enroll in public + specified courses.",
    )
    parser.add_argument("--csv", required=True, type=Path, help="Path to CSV file (username,display_name,invite_codes)")
    parser.add_argument("--domain", default="knoweia.com", help="Email domain (default: knoweia.com)")
    parser.add_argument("--password", required=True, help="Shared password for all users")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing to DB")
    return parser.parse_args()


def load_users_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            username = row.get("username", "").strip()
            display_name = row.get("display_name", "").strip()
            invite_codes_raw = row.get("invite_codes", "").strip()
            if not username:
                continue
            invite_codes = [c.strip().upper() for c in invite_codes_raw.split(";") if c.strip()] if invite_codes_raw else []
            users.append({"username": username, "display_name": display_name or username, "invite_codes": invite_codes})
    return users


def main() -> int:
    args = parse_args()
    csv_path: Path = args.csv.resolve()
    domain = args.domain.strip().lstrip("@")
    password = args.password

    if not csv_path.is_file():
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    if len(password) < 8:
        print("Error: password must be at least 8 characters", file=sys.stderr)
        return 2

    users = load_users_from_csv(csv_path)
    if not users:
        print("Error: no users found in CSV", file=sys.stderr)
        return 1

    print(f"Loaded {len(users)} user(s) from {csv_path.name}")

    with SessionLocal() as db:
        # Public active courses — auto-enroll everyone
        public_courses = db.execute(
            select(Course).where(Course.is_active.is_(True), Course.is_public.is_(True))
        ).scalars().all()

        # Build invite_code -> Course lookup for specific enrollments
        all_invite_codes = set()
        for u in users:
            all_invite_codes.update(u["invite_codes"])

        invite_course_map: dict[str, Course] = {}
        if all_invite_codes:
            specific_courses = db.execute(
                select(Course).where(Course.invite_code.in_(all_invite_codes), Course.is_active.is_(True))
            ).scalars().all()
            invite_course_map = {c.invite_code: c for c in specific_courses if c.invite_code}

            # Warn about unknown invite codes
            found_codes = set(invite_course_map.keys())
            missing = all_invite_codes - found_codes
            if missing:
                print(f"Warning: unknown invite codes: {', '.join(sorted(missing))}")

        print(f"Public courses: {len(public_courses)}")
        for c in public_courses:
            print(f"  [{c.invite_code}] {c.title}")
        if invite_course_map:
            print(f"Specific courses: {len(invite_course_map)}")
            for code, c in invite_course_map.items():
                print(f"  [{code}] {c.title}")

        if args.dry_run:
            print("\n=== DRY RUN — no changes will be written ===\n")
            for u in users:
                email = f"{u['username']}@{domain}"
                print(f"  User: {email}  ({u['display_name']})")
                for c in public_courses:
                    print(f"    → [public] {c.title}")
                for code in u["invite_codes"]:
                    c = invite_course_map.get(code)
                    if c:
                        print(f"    → [invite] {c.title}")
                    else:
                        print(f"    → [invite] {code} (NOT FOUND)")
            return 0

        pw_hash = hash_password(password)
        results = []

        for u in users:
            email = f"{u['username']}@{domain}"
            display_name = u["display_name"]

            # Create or update user
            user = db.execute(select(User).where(User.email == email)).scalars().first()
            if user:
                user.display_name = display_name
                user.password_hash = pw_hash
                user.status = "active"
                created = False
            else:
                user = User(email=email, display_name=display_name, password_hash=pw_hash, status="active")
                db.add(user)
                db.flush()
                created = True

            # Collect courses to enroll: public + specific
            target_courses: list[Course] = list(public_courses)
            for code in u["invite_codes"]:
                c = invite_course_map.get(code)
                if c and c not in target_courses:
                    target_courses.append(c)

            enrolled_titles: list[str] = []
            for course in target_courses:
                existing = db.execute(
                    select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id)
                ).scalars().first()
                if not existing:
                    db.add(Enrollment(user_id=user.id, course_id=course.id, status="active"))
                    enrolled_titles.append(course.title)

            results.append({"email": email, "display_name": display_name, "created": created, "enrolled_in": enrolled_titles})

        db.commit()

    # Print summary
    print(f"\nDone. {len(results)} users processed.\n")
    for r in results:
        action = "CREATED" if r["created"] else "UPDATED"
        print(f"  [{action}] {r['email']} ({r['display_name']})")
        if r["enrolled_in"]:
            print(f"           enrolled in: {', '.join(r['enrolled_in'])}")
        else:
            print("           (already enrolled in all target courses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
