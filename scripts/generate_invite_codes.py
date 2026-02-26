#!/usr/bin/env python3
"""Generate invite codes via the admin API.

Usage:
    python scripts/generate_invite_codes.py --count 1000
    python scripts/generate_invite_codes.py --count 50 --output codes.txt

Environment variables:
    ADMIN_API_KEY   - Required. The admin key for the backend API.
    BASE_URL        - Backend base URL (default: http://47.93.151.131:10723)
"""

import argparse
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("BASE_URL", "http://47.93.151.131:10723").rstrip("/")
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")


def api_post(path: str, payload: dict) -> dict:
    if not ADMIN_KEY:
        print("Error: ADMIN_API_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)
    data = json.dumps(payload).encode()
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"X-Admin-Key": ADMIN_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Error: HTTP {e.code} - {body}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate invite codes via admin API")
    parser.add_argument("--count", type=int, default=1000, help="Number of codes to generate (default: 1000)")
    parser.add_argument("--output", "-o", type=str, help="Write codes to file (one per line)")
    args = parser.parse_args()

    # The API supports batch generation; generate in chunks of 500
    all_codes: list[str] = []
    remaining = args.count
    batch_size = 500

    while remaining > 0:
        n = min(remaining, batch_size)
        print(f"Generating {n} codes ({len(all_codes)}/{args.count} done)...")
        result = api_post("/v1/admin/invite-codes/generate", {"count": n})
        codes = result.get("codes", [])
        all_codes.extend(codes)
        remaining -= len(codes)
        if len(codes) < n:
            print(f"Warning: requested {n} but got {len(codes)}", file=sys.stderr)
            break

    print(f"\nGenerated {len(all_codes)} invite codes.")

    if args.output:
        with open(args.output, "w") as f:
            for code in all_codes:
                f.write(code + "\n")
        print(f"Saved to {args.output}")
    else:
        for code in all_codes:
            print(code)


if __name__ == "__main__":
    main()
