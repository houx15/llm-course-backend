"""Create users from CSV via the admin API.

CSV format (header required):
    username,display_name,password,invite_codes
    pangxun,庞珣,MyPass123!,
    tangshiyun,唐诗韵,HerPass456!,ABC123;DEF456

- password: per-user password (required, min 8 chars)
- invite_codes: semicolon-separated course invite codes (optional)
- All users are auto-enrolled in public active courses by the server

Usage:
    python app/scripts/create_batch_users.py \\
        --csv users.csv --server http://... --admin-key KEY

    python app/scripts/create_batch_users.py \\
        --csv users.csv --server http://... --admin-key KEY --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create users from CSV via admin API.")
    parser.add_argument("--csv", required=True, type=Path, help="CSV file (username,display_name,password,invite_codes)")
    parser.add_argument("--server", required=True, help="Backend URL, e.g. http://47.93.151.131:10723")
    parser.add_argument("--admin-key", required=True, help="Admin API key")
    parser.add_argument("--domain", default="knoweia.com", help="Email domain (default: knoweia.com)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent without calling the API")
    return parser.parse_args()


def load_users_from_csv(csv_path: Path, domain: str) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            username = row.get("username", "").strip()
            display_name = row.get("display_name", "").strip()
            password = row.get("password", "").strip()
            invite_codes_raw = row.get("invite_codes", "").strip()
            if not username:
                continue
            if not password or len(password) < 8:
                print(f"Error: row {i} ({username}): password missing or < 8 chars", file=sys.stderr)
                return []
            invite_codes = [c.strip().upper() for c in invite_codes_raw.split(";") if c.strip()] if invite_codes_raw else []
            users.append({
                "email": f"{username}@{domain}",
                "display_name": display_name or username,
                "password": password,
                "invite_codes": invite_codes,
            })
    return users


def main() -> int:
    args = parse_args()
    csv_path: Path = args.csv.resolve()
    domain = args.domain.strip().lstrip("@")
    server = args.server.rstrip("/")

    if not csv_path.is_file():
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    users = load_users_from_csv(csv_path, domain)
    if not users:
        print("Error: no valid users found in CSV", file=sys.stderr)
        return 1

    print(f"Loaded {len(users)} user(s) from {csv_path.name}")
    for u in users:
        codes = "; ".join(u["invite_codes"]) if u["invite_codes"] else "(public only)"
        print(f"  {u['email']}  ({u['display_name']})  courses: {codes}")

    if args.dry_run:
        print("\n[dry-run] No API calls made.")
        return 0

    payload = {"users": users}

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{server}/v1/admin/users/batch",
            json=payload,
            headers={"X-Admin-Key": args.admin_key},
        )

    if resp.status_code != 201:
        print(f"Error: HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        return 1

    data = resp.json()
    results = data.get("results", [])
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
