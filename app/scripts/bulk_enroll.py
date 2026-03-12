#!/usr/bin/env python3
"""
Enroll all active users (or specific users) into a course via admin API.

Usage:
    # Enroll ALL active users into a course by course_id:
    python bulk_enroll.py --server http://47.93.151.131:10723 --admin-key KEY \\
        --course-id db881a93-47c1-4e51-8630-43902e505b39

    # Enroll ALL active users using invite code (resolves to course_id automatically):
    python bulk_enroll.py --server http://47.93.151.131:10723 --admin-key KEY \\
        --invite-code 1Q16CR

    # Enroll specific users by email:
    python bulk_enroll.py --server http://47.93.151.131:10723 --admin-key KEY \\
        --course-id UUID --emails alice@example.com bob@example.com

    # Dry-run:
    python bulk_enroll.py --server http://47.93.151.131:10723 --admin-key KEY \\
        --invite-code 1Q16CR --dry-run
"""

from __future__ import annotations

import argparse
import sys

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk-enroll users into a course via admin API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--server", required=True, help="Backend server URL")
    parser.add_argument("--admin-key", required=True, help="Admin API key")

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--course-id", help="Course UUID to enroll into")
    target.add_argument("--invite-code", help="Course invite code (resolves to course_id)")

    parser.add_argument("--emails", nargs="+", metavar="EMAIL", help="Enroll only these users (by email). Omit to enroll all active users.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    return parser.parse_args()


def resolve_course_id(client: httpx.Client, server: str, admin_key: str, invite_code: str) -> tuple[str, str]:
    """Resolve invite_code → (course_id, title) by listing all courses."""
    resp = client.get(f"{server}/v1/admin/courses", headers={"X-Admin-Key": admin_key})
    if resp.status_code != 200:
        print(f"Error: failed to list courses: HTTP {resp.status_code}", file=sys.stderr)
        sys.exit(1)
    for course in resp.json().get("courses", []):
        if course.get("invite_code", "").upper() == invite_code.upper():
            return course["id"], course["title"]
    print(f"Error: no active course found with invite code '{invite_code}'", file=sys.stderr)
    sys.exit(1)


def resolve_user_ids(client: httpx.Client, server: str, admin_key: str, emails: list[str]) -> list[str]:
    """Resolve email addresses → user IDs."""
    resp = client.get(f"{server}/v1/admin/users", headers={"X-Admin-Key": admin_key})
    if resp.status_code != 200:
        print(f"Error: failed to list users: HTTP {resp.status_code}", file=sys.stderr)
        sys.exit(1)
    email_set = {e.lower().strip() for e in emails}
    user_ids: list[str] = []
    found_emails: set[str] = set()
    for user in resp.json().get("users", []):
        if user["email"].lower() in email_set:
            user_ids.append(user["id"])
            found_emails.add(user["email"].lower())
    missing = email_set - found_emails
    if missing:
        print(f"Warning: users not found: {', '.join(sorted(missing))}")
    return user_ids


def main() -> int:
    args = parse_args()
    server = args.server.rstrip("/")
    headers = {"X-Admin-Key": args.admin_key}

    with httpx.Client(timeout=30.0) as client:
        # Resolve course
        if args.invite_code:
            course_id, title = resolve_course_id(client, server, args.admin_key, args.invite_code)
            print(f"Resolved invite code '{args.invite_code}' → {title} ({course_id})")
        else:
            course_id = args.course_id
            title = course_id

        # Resolve users if specific emails given
        user_ids = None
        if args.emails:
            user_ids = resolve_user_ids(client, server, args.admin_key, args.emails)
            if not user_ids:
                print("Error: no matching users found", file=sys.stderr)
                return 1
            print(f"Resolved {len(user_ids)} user(s) from {len(args.emails)} email(s)")
        else:
            print("Target: ALL active users")

        if args.dry_run:
            print(f"\n[dry-run] Would enroll {'all active users' if not user_ids else f'{len(user_ids)} users'} into course {title}")
            return 0

        # Call bulk-enroll endpoint
        payload: dict = {"course_id": course_id}
        if user_ids is not None:
            payload["user_ids"] = user_ids

        resp = client.post(
            f"{server}/v1/admin/users/bulk-enroll",
            json=payload,
            headers=headers,
        )

        if resp.status_code != 200:
            print(f"Error: bulk-enroll failed: HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
            return 1

        data = resp.json()
        print(f"\nCourse: {data['course_title']}")
        print(f"Newly enrolled : {data['enrolled']}")
        print(f"Already enrolled: {data['already_enrolled']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
