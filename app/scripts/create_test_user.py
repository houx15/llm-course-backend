from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly: `python app/scripts/create_test_user.py`
if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Course, Enrollment, User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update a test user for local/dev verification.")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--password", required=True, help="Plain password (will be hashed)")
    parser.add_argument("--name", default="", help="Display name (optional)")
    parser.add_argument("--course-code", default="", help="Optional course code to auto-enroll, e.g. SOC101")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    email = args.email.strip().lower()
    password = args.password
    display_name = args.name.strip() or email.split("@")[0]
    course_code = args.course_code.strip().upper()

    if len(password) < 8:
        print("Error: password must be at least 8 characters", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalars().first()
        created = False
        if not user:
            user = User(
                email=email,
                display_name=display_name,
                password_hash=hash_password(password),
                status="active",
            )
            db.add(user)
            db.flush()
            created = True
        else:
            user.display_name = display_name
            user.password_hash = hash_password(password)
            if user.status != "active":
                user.status = "active"
            db.add(user)

        enrolled = False
        if course_code:
            course = db.execute(
                select(Course).where(Course.course_code == course_code, Course.is_active.is_(True))
            ).scalars().first()
            if not course:
                print(f"Error: course not found or inactive: {course_code}", file=sys.stderr)
                db.rollback()
                return 3

            existing_enrollment = db.execute(
                select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id)
            ).scalars().first()
            if not existing_enrollment:
                db.add(
                    Enrollment(
                        user_id=user.id,
                        course_id=course.id,
                        status="active",
                    )
                )
                enrolled = True

        db.commit()

    print(
        {
            "ok": True,
            "created": created,
            "email": email,
            "display_name": display_name,
            "course_code": course_code or None,
            "enrolled": enrolled,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
