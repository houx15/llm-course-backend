"""Create multiple test users and enroll them in all active courses.

Usage:
    uv run python app/scripts/create_batch_users.py
    uv run python app/scripts/create_batch_users.py --domain example.com --password MyPass123
    uv run python app/scripts/create_batch_users.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Course, Enrollment, User

# ── Users to create ───────────────────────────────────────────────────────────

USERS = [
    {"username": "pangxun", "display_name": "庞珣"},
    {"username": "tangshiyun", "display_name": "唐诗韵"},
    {"username": "marunyi", "display_name": "马润艺"},
    {"username": "hujingtian", "display_name": "胡竞天"},
    {"username": "chengkaiyue", "display_name": "程凯越"},
    {"username": "houyuxin", "display_name": "侯煜欣"},
]

# ─────────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create batch test users and enroll them in all active courses."
    )
    parser.add_argument(
        "--domain", default="knoweia.com", help="Email domain (default: knoweia.com)"
    )
    parser.add_argument(
        "--password",
        default="Knoweia2025!",
        help="Shared password for all users (default: Knoweia2025!)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing to DB",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    domain = args.domain.strip().lstrip("@")
    password = args.password

    if len(password) < 8:
        print("Error: password must be at least 8 characters", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        # Fetch all active courses once
        courses = (
            db.execute(select(Course).where(Course.is_active.is_(True))).scalars().all()
        )
        if not courses:
            print(
                "Warning: no active courses found — users will be created but not enrolled."
            )

        if args.dry_run:
            print("=== DRY RUN — no changes will be written ===\n")
            for u in USERS:
                email = f"{u['username']}@{domain}"
                print(f"  User: {email!r}  display_name={u['display_name']!r}")
                for c in courses:
                    print(f"    → enroll in {c.course_code!r} ({c.title})")
            return 0

        pw_hash = hash_password(password)
        results = []

        for u in USERS:
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
                user = User(
                    email=email,
                    display_name=display_name,
                    password_hash=pw_hash,
                    status="active",
                )
                db.add(user)
                db.flush()
                created = True

            # Enroll in all active courses
            enrolled_codes: list[str] = []
            for course in courses:
                existing = (
                    db.execute(
                        select(Enrollment).where(
                            Enrollment.user_id == user.id,
                            Enrollment.course_id == course.id,
                        )
                    )
                    .scalars()
                    .first()
                )
                if not existing:
                    db.add(
                        Enrollment(
                            user_id=user.id, course_id=course.id, status="active"
                        )
                    )
                    enrolled_codes.append(course.course_code)

            results.append(
                {
                    "email": email,
                    "display_name": display_name,
                    "created": created,
                    "enrolled_in": enrolled_codes,
                }
            )

        db.commit()

    # Print summary
    print(f"\nDone. {len(results)} users processed.\n")
    for r in results:
        action = "CREATED" if r["created"] else "UPDATED"
        print(f"  [{action}] {r['email']} ({r['display_name']})")
        if r["enrolled_in"]:
            print(f"           enrolled in: {', '.join(r['enrolled_in'])}")
        else:
            print("           (already enrolled in all courses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
