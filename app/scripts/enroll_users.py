#!/usr/bin/env python3
"""
Batch-create users and/or enroll them in a course.

Usage:
    # From a CSV file (columns: email, name, password — password optional):
    uv run python app/scripts/enroll_users.py --course-code SOC101 --csv students.csv

    # From inline emails (auto-generates a temporary password):
    uv run python app/scripts/enroll_users.py --course-code SOC101 \\
        --emails alice@example.com bob@example.com

    # Enroll only (skip user creation for existing accounts):
    uv run python app/scripts/enroll_users.py --course-code SOC101 --csv students.csv --enroll-only

    # Dry-run (print what would happen):
    uv run python app/scripts/enroll_users.py --course-code SOC101 --csv students.csv --dry-run

CSV format (header row required):
    email,name,password
    alice@example.com,Alice Wang,MyPass123
    bob@example.com,Bob Li,         <- password column optional; auto-generates if blank
"""

from __future__ import annotations

import argparse
import csv
import secrets
import string
import sys
from pathlib import Path
from typing import NamedTuple

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Course, Enrollment, User


class StudentRow(NamedTuple):
    email: str
    name: str
    password: str  # plain text; empty means auto-generate


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch create users and enroll them in a course",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--course-code", required=True, help="Course code to enroll into, e.g. SOC101")

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, metavar="FILE", help="CSV file with columns: email[,name[,password]]")
    source.add_argument("--emails", nargs="+", metavar="EMAIL", help="Space-separated list of email addresses")

    parser.add_argument("--default-name", default="", help="Default display name when name column is absent")
    parser.add_argument("--default-password", default="", help="Default password when password column absent/empty")
    parser.add_argument("--enroll-only", action="store_true", help="Skip user creation; only enroll existing accounts")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without writing to DB")
    return parser.parse_args()


def load_csv(path: Path, default_name: str, default_password: str) -> list[StudentRow]:
    if not path.exists():
        print(f"Error: CSV file not found: {path}", file=sys.stderr)
        sys.exit(1)
    rows: list[StudentRow] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("Error: CSV file is empty", file=sys.stderr)
            sys.exit(1)
        # Normalize header names to lowercase
        fieldnames_lower = [h.strip().lower() for h in reader.fieldnames]
        for i, row in enumerate(reader, start=2):
            norm = {k.strip().lower(): v.strip() for k, v in row.items()}
            email = norm.get("email", "").lower()
            if not email:
                print(f"Warning: row {i} has no email, skipping")
                continue
            name = norm.get("name", "") or default_name or email.split("@")[0]
            password = norm.get("password", "") or default_password
            rows.append(StudentRow(email=email, name=name, password=password))
    return rows


def load_emails(emails: list[str], default_name: str, default_password: str) -> list[StudentRow]:
    rows: list[StudentRow] = []
    for email in emails:
        email = email.strip().lower()
        if not email:
            continue
        name = default_name or email.split("@")[0]
        rows.append(StudentRow(email=email, name=name, password=default_password))
    return rows


def main() -> int:
    args = parse_args()
    course_code = args.course_code.strip().upper()

    if args.csv:
        students = load_csv(args.csv, args.default_name, args.default_password)
    else:
        students = load_emails(args.emails, args.default_name, args.default_password)

    if not students:
        print("No students to process.", file=sys.stderr)
        return 1

    print(f"Processing {len(students)} student(s) → course {course_code}")
    if args.dry_run:
        print("[dry-run] Would process:")
        for s in students:
            pw_note = "(auto-generate)" if not s.password else "(provided)"
            print(f"  {s.email}  name={s.name!r}  password={pw_note}")
        print("\n[dry-run] No changes made.")
        return 0

    with SessionLocal() as db:
        # Verify course exists
        course = db.execute(
            select(Course).where(Course.course_code == course_code, Course.is_active.is_(True))
        ).scalars().first()
        if not course:
            print(f"Error: course not found or inactive: {course_code}", file=sys.stderr)
            return 1

        results: list[dict] = []
        for s in students:
            row: dict = {"email": s.email, "user_created": False, "enrolled": False, "password": ""}

            # Resolve user
            user = db.execute(select(User).where(User.email == s.email)).scalars().first()
            if not user:
                if args.enroll_only:
                    row["error"] = "user not found (--enroll-only set)"
                    results.append(row)
                    continue
                plain_pw = s.password or _generate_password()
                row["password"] = plain_pw
                user = User(
                    email=s.email,
                    display_name=s.name or s.email.split("@")[0],
                    password_hash=hash_password(plain_pw),
                    status="active",
                )
                db.add(user)
                db.flush()
                row["user_created"] = True

            # Enroll if not already enrolled
            existing_enrollment = db.execute(
                select(Enrollment).where(
                    Enrollment.user_id == user.id,
                    Enrollment.course_id == course.id,
                )
            ).scalars().first()
            if not existing_enrollment:
                db.add(Enrollment(user_id=user.id, course_id=course.id, status="active"))
                row["enrolled"] = True

            results.append(row)

        db.commit()

    # Summary
    created = sum(1 for r in results if r.get("user_created"))
    enrolled = sum(1 for r in results if r.get("enrolled"))
    errors = sum(1 for r in results if r.get("error"))

    print(f"\nUsers created : {created}")
    print(f"Newly enrolled: {enrolled}")
    if errors:
        print(f"Errors        : {errors}")

    # Print credentials for newly created users
    new_users = [r for r in results if r.get("user_created") and r.get("password")]
    if new_users:
        print("\nGenerated credentials (save these!):")
        print(f"  {'email':<35}  password")
        print(f"  {'-'*35}  {'--------'}")
        for r in new_users:
            print(f"  {r['email']:<35}  {r['password']}")

    if errors:
        print("\nErrors:")
        for r in results:
            if r.get("error"):
                print(f"  {r['email']}: {r['error']}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
