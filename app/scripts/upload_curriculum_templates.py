#!/usr/bin/env python3
"""
Package and upload the curriculum report templates as an app_agents bundle.

The templates (dynamic_report_template.md, final_learning_report_template.md,
student_error_summary_template.md) are placed at the bundle root so that
CURRICULUM_TEMPLATES_DIR can point directly to the installed bundle path.

Usage:
    uv run python app/scripts/upload_curriculum_templates.py \\
        --templates-dir /path/to/demo/curriculum/_templates \\
        --server http://47.93.151.131:10723 \\
        --admin-key YOUR_KEY \\
        --version 1.0.0
"""

from __future__ import annotations

import argparse
import gzip
import io
import sys
import tarfile
from pathlib import Path

import httpx

EXPECTED_FILES = {
    "dynamic_report_template.md",
    "final_learning_report_template.md",
    "student_error_summary_template.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and upload curriculum templates bundle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--templates-dir",
        required=True,
        type=Path,
        help="Directory containing the 3 template .md files",
    )
    parser.add_argument("--server", required=True, help="Backend URL, e.g. http://47.93.151.131:10723")
    parser.add_argument("--admin-key", required=True, help="Admin API key")
    parser.add_argument("--version", required=True, help="Bundle version, e.g. 1.0.0")
    parser.add_argument("--dry-run", action="store_true", help="Build bundle but skip upload")
    return parser.parse_args()


def build_bundle(templates_dir: Path) -> bytes:
    """Package template files into a tar.gz. Files sit at the archive root."""
    missing = EXPECTED_FILES - {f.name for f in templates_dir.iterdir() if f.is_file()}
    if missing:
        print(f"Warning: missing template files: {sorted(missing)}")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(templates_dir.iterdir()):
            if path.is_file() and path.suffix == ".md":
                tar.add(str(path), arcname=path.name)
    return buf.getvalue()


def upload(server: str, admin_key: str, bundle_bytes: bytes, version: str) -> dict:
    url = f"{server.rstrip('/')}/v1/admin/bundles/upload"
    files = {"file": (f"curriculum_templates_{version}.tar.gz", bundle_bytes, "application/gzip")}
    data = {
        "bundle_type": "app_agents",
        "scope_id": "curriculum_templates",
        "version": version,
        "is_mandatory": "false",   # optional — app works without it (falls back to built-ins)
        "manifest_json": "{}",
    }
    headers = {"X-Admin-Key": admin_key}

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, files=files, data=data, headers=headers)

    if response.status_code == 201:
        return response.json()
    raise RuntimeError(f"Upload failed HTTP {response.status_code}: {response.text[:300]}")


def main() -> int:
    args = parse_args()
    templates_dir = args.templates_dir.resolve()

    if not templates_dir.is_dir():
        print(f"Error: templates directory not found: {templates_dir}", file=sys.stderr)
        return 1

    print(f"Templates dir : {templates_dir}")
    print(f"Files         : {[f.name for f in sorted(templates_dir.iterdir()) if f.suffix == '.md']}")
    print(f"Version       : {args.version}")

    bundle_bytes = build_bundle(templates_dir)
    print(f"Bundle size   : {len(bundle_bytes):,} bytes")

    if args.dry_run:
        print("\n[dry-run] Skipping upload.")
        return 0

    try:
        result = upload(args.server, args.admin_key, bundle_bytes, args.version)
        print(f"\nUploaded!")
        print(f"  id           : {result.get('id')}")
        print(f"  artifact_url : {result.get('artifact_url')}")
    except Exception as e:
        print(f"Upload failed: {e}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
