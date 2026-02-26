#!/usr/bin/env python3
"""Fetch a bug report by ID and pretty-print it. Optionally download the log file.

Usage:
    python scripts/get_bug_report.py BUG-A3F2K1
    python scripts/get_bug_report.py BUG-A3F2K1 --download
    python scripts/get_bug_report.py --list
    python scripts/get_bug_report.py --list --limit 10

Environment variables:
    ADMIN_API_KEY   - Required. The admin key for the backend API.
    BASE_URL        - Backend base URL (default: http://47.93.151.131:10723)
"""

import argparse
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError


BASE_URL = os.environ.get("BASE_URL", "http://47.93.151.131:10723").rstrip("/")
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")


def api_get(path: str) -> dict:
    if not ADMIN_KEY:
        print("Error: ADMIN_API_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)
    req = Request(f"{BASE_URL}{path}", headers={"X-Admin-Key": ADMIN_KEY})
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Error: HTTP {e.code} - {body}", file=sys.stderr)
        sys.exit(1)


def download_file(url: str, dest: str) -> None:
    req = Request(url)
    with urlopen(req) as resp:
        with open(dest, "wb") as f:
            while chunk := resp.read(8192):
                f.write(chunk)


def cmd_get(bug_id: str, do_download: bool) -> None:
    report = api_get(f"/v1/admin/bugs/reports/{bug_id}")

    print(f"Bug ID:      {report['bug_id']}")
    print(f"Created:     {report['created_at']}")
    print(f"User:        {report.get('user_email') or report.get('user_id') or 'N/A'}")
    print(f"Platform:    {report.get('platform') or 'N/A'}")
    print(f"App Version: {report.get('app_version') or 'N/A'}")
    print(f"Size:        {report.get('file_size_bytes', 0):,} bytes")
    print(f"Description: {report.get('description') or 'N/A'}")
    if report.get("metadata"):
        print(f"Metadata:    {json.dumps(report['metadata'], indent=2)}")
    print(f"OSS Key:     {report.get('oss_key') or 'N/A'}")
    print(f"Download:    {report.get('download_url') or 'N/A'}")

    if do_download and report.get("download_url"):
        dest = f"{bug_id}.json"
        print(f"\nDownloading log to {dest} ...")
        download_file(report["download_url"], dest)
        print(f"Saved to {dest}")

        # Pretty-print the log content
        try:
            with open(dest) as f:
                log_data = json.load(f)
            print("\n--- Log Content ---")
            print(json.dumps(log_data, indent=2, ensure_ascii=False))
        except (json.JSONDecodeError, OSError):
            print(f"(Downloaded file is not valid JSON, saved raw to {dest})")


def cmd_list(limit: int, offset: int) -> None:
    data = api_get(f"/v1/admin/bugs/reports?limit={limit}&offset={offset}")
    total = data.get("total", 0)
    reports = data.get("reports", [])
    print(f"Total: {total}  (showing {len(reports)})\n")

    if not reports:
        print("No bug reports found.")
        return

    for r in reports:
        user = r.get("user_email") or r.get("user_id") or "N/A"
        print(
            f"  {r['bug_id']}  {r['created_at'][:19]}  "
            f"{r.get('platform', ''):<16s}  "
            f"{r.get('app_version', ''):<16s}  "
            f"{user}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch bug reports from the admin API")
    parser.add_argument("bug_id", nargs="?", help="Bug ID to fetch (e.g. BUG-A3F2K1)")
    parser.add_argument("--download", action="store_true", help="Download and display the log file")
    parser.add_argument("--list", action="store_true", help="List recent bug reports")
    parser.add_argument("--limit", type=int, default=20, help="Number of reports to list (default: 20)")
    parser.add_argument("--offset", type=int, default=0, help="Offset for pagination")
    args = parser.parse_args()

    if args.list:
        cmd_list(args.limit, args.offset)
    elif args.bug_id:
        cmd_get(args.bug_id, args.download)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
