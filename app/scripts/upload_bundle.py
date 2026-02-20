#!/usr/bin/env python3
"""
Upload bundle to remote server via /v1/admin/bundles/upload API.

Can accept either a directory (will be zipped to .tar.gz) or an existing .tar.gz file.

Usage with directory (auto-zip):
    uv run python app/scripts/upload_bundle.py \
        --server https://api.example.com \
        --admin-key YOUR_ADMIN_KEY \
        --source ./bundles/ch1_intro \
        --bundle-type chapter \
        --scope-id SOC101/ch1_intro \
        --version 1.0.0

Usage with existing .tar.gz:
    uv run python app/scripts/upload_bundle.py \
        --server https://api.example.com \
        --admin-key YOUR_ADMIN_KEY \
        --source ./bundles/ch1_intro.tar.gz \
        --bundle-type chapter \
        --scope-id SOC101/ch1_intro \
        --version 1.0.0
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import sys
import tarfile
from pathlib import Path

import httpx


BUNDLE_TYPES = ["chapter", "app_agents", "experts", "experts_shared", "python_runtime"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload bundle to server via admin API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--server", required=True, help="Server base URL, e.g. https://api.example.com"
    )
    parser.add_argument(
        "--admin-key", required=True, help="Admin API key (X-Admin-Key header)"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to bundle directory or .tar.gz file. If directory, will be zipped automatically.",
    )
    parser.add_argument(
        "--bundle-type",
        required=True,
        choices=BUNDLE_TYPES,
        help=f"Bundle type: {', '.join(BUNDLE_TYPES)}",
    )
    parser.add_argument(
        "--scope-id",
        required=True,
        help="Scope ID, e.g. SOC101/ch1_intro or data_inspector",
    )
    parser.add_argument("--version", required=True, help="Semantic version, e.g. 1.0.0")
    parser.add_argument(
        "--mandatory",
        action="store_true",
        default=True,
        help="Mark as mandatory (default: True)",
    )
    parser.add_argument(
        "--no-mandatory",
        dest="mandatory",
        action="store_false",
        help="Mark as optional",
    )
    parser.add_argument(
        "--manifest",
        default="{}",
        help='JSON manifest, e.g. \'{"required_experts": ["data_inspector"]}\'',
    )
    parser.add_argument(
        "--keep-tar",
        action="store_true",
        help="Keep the generated .tar.gz file after upload (only when source is a directory)",
    )
    return parser.parse_args()


def create_tar_gz(source_dir: Path) -> tuple[bytes, str]:
    """
    Create a tar.gz archive from a directory.
    Returns (archive_bytes, filename).
    """
    if not source_dir.is_dir():
        raise ValueError(f"Not a directory: {source_dir}")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in source_dir.iterdir():
            if item.name.startswith("."):
                continue
            tar.add(item, arcname=item.name)

    filename = f"{source_dir.name}.tar.gz"
    return buf.getvalue(), filename


def main() -> int:
    args = parse_args()

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: source not found: {source_path}", file=sys.stderr)
        return 1

    if source_path.is_dir():
        print(f"Creating tar.gz from directory: {source_path}")
        try:
            archive_bytes, filename = create_tar_gz(source_path)
        except Exception as e:
            print(f"Error creating archive: {e}", file=sys.stderr)
            return 1
        print(f"Created archive: {filename} ({len(archive_bytes):,} bytes)")

        if args.keep_tar:
            tar_path = source_path.parent / filename
            tar_path.write_bytes(archive_bytes)
            print(f"Saved to: {tar_path}")

    elif source_path.is_file():
        if not source_path.name.lower().endswith(".tar.gz"):
            print("Error: file must have .tar.gz extension", file=sys.stderr)
            return 1
        archive_bytes = source_path.read_bytes()
        filename = source_path.name
        print(f"Using existing archive: {filename} ({len(archive_bytes):,} bytes)")

    else:
        print(
            f"Error: source is neither a file nor directory: {source_path}",
            file=sys.stderr,
        )
        return 1

    server = args.server.rstrip("/")
    url = f"{server}/v1/admin/bundles/upload"

    files = {"file": (filename, archive_bytes, "application/gzip")}
    data = {
        "bundle_type": args.bundle_type,
        "scope_id": args.scope_id,
        "version": args.version,
        "is_mandatory": "true" if args.mandatory else "false",
        "manifest_json": args.manifest,
    }
    headers = {"X-Admin-Key": args.admin_key}

    print(f"\nUploading to {url}...")
    print(f"  bundle_type: {args.bundle_type}")
    print(f"  scope_id: {args.scope_id}")
    print(f"  version: {args.version}")

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, files=files, data=data, headers=headers)
    except httpx.ConnectError as e:
        print(f"Error: cannot connect to server: {e}", file=sys.stderr)
        return 1
    except httpx.TimeoutException:
        print("Error: request timed out", file=sys.stderr)
        return 1

    if response.status_code == 201:
        result = response.json()
        print("\nUpload successful!")
        print(f"  id: {result.get('id')}")
        print(f"  artifact_url: {result.get('artifact_url')}")
        print(f"  created_at: {result.get('created_at')}")
        return 0
    else:
        print(f"\nUpload failed: HTTP {response.status_code}", file=sys.stderr)
        try:
            error = response.json()
            print(f"  code: {error.get('code')}")
            print(f"  message: {error.get('message')}", file=sys.stderr)
        except Exception:
            print(f"  response: {response.text}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
