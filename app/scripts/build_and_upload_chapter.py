#!/usr/bin/env python3
"""
Build a chapter bundle from a curriculum directory and upload it to the backend.

This is the single command for publishing chapter content. It combines
build_chapter_bundle.py (packaging) with the bundle upload API call.

Usage:
    uv run python app/scripts/build_and_upload_chapter.py \\
        --chapter-dir /path/to/demo/curriculum/courses/course2/chapters/ch2_python_basis \\
        --server http://47.93.151.131:10723 \\
        --admin-key YOUR_KEY \\
        --version 1.0.0

    # Auto-version from git commit count (requires git in PATH):
    uv run python app/scripts/build_and_upload_chapter.py \\
        --chapter-dir /path/to/chapters/ch2_python_basis \\
        --server http://47.93.151.131:10723 \\
        --admin-key YOUR_KEY \\
        --auto-version

    # Build all chapters in a course at once:
    uv run python app/scripts/build_and_upload_chapter.py \\
        --course-dir /path/to/demo/curriculum/courses/course2_political_data_analysis \\
        --server http://47.93.151.131:10723 \\
        --admin-key YOUR_KEY \\
        --version 1.0.0
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

import httpx

# Import build logic from sibling script
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))
from build_chapter_bundle import build_chapter_bundle  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and upload a chapter bundle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--chapter-dir", type=Path, help="Single chapter directory to build")
    target.add_argument("--course-dir", type=Path, help="Course directory — builds ALL chapters found")

    parser.add_argument("--server", required=True, help="Backend server URL, e.g. http://47.93.151.131:10723")
    parser.add_argument("--admin-key", required=True, help="Admin API key (X-Admin-Key header)")

    version_group = parser.add_mutually_exclusive_group(required=True)
    version_group.add_argument("--version", help="Explicit semantic version, e.g. 1.0.0")
    version_group.add_argument(
        "--auto-version",
        action="store_true",
        help="Derive version from pyproject.toml + git commit count (e.g. 0.1.0-build.42)",
    )

    parser.add_argument("--scope-id", default=None, help="Override scope_id (default: course_id/chapter_code)")
    parser.add_argument("--dry-run", action="store_true", help="Build bundle but skip upload")
    parser.add_argument("--keep-bundle", action="store_true", help="Keep the .tar.gz after upload")
    return parser.parse_args()


def _auto_version() -> str:
    """Derive version from pyproject.toml + git commit count."""
    try:
        import tomllib
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pyproject.exists():
            with pyproject.open("rb") as f:
                data = tomllib.load(f)
            base = data.get("project", {}).get("version", "0.1.0")
        else:
            base = "0.1.0"
    except Exception:
        base = "0.1.0"

    try:
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        count = "0"

    return f"{base}-build.{count}"


def _upload(server: str, admin_key: str, bundle_path: Path, scope_id: str, version: str) -> dict:
    url = f"{server.rstrip('/')}/v1/admin/bundles/upload"
    with bundle_path.open("rb") as f:
        bundle_bytes = f.read()

    files = {"file": (bundle_path.name, bundle_bytes, "application/gzip")}
    data = {
        "bundle_type": "chapter",
        "scope_id": scope_id,
        "version": version,
        "is_mandatory": "true",
        "manifest_json": "{}",
    }
    headers = {"X-Admin-Key": admin_key}

    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, files=files, data=data, headers=headers)

    if response.status_code == 201:
        return response.json()
    raise RuntimeError(f"Upload failed HTTP {response.status_code}: {response.text[:300]}")


def build_and_upload_one(
    chapter_dir: Path,
    server: str,
    admin_key: str,
    version: str,
    scope_id_override: str | None,
    dry_run: bool,
    keep_bundle: bool,
    output_dir: Path,
) -> bool:
    chapter_dir = chapter_dir.resolve()
    print(f"\n{'='*60}")
    print(f"Chapter: {chapter_dir.name}")

    try:
        bundle_path, manifest = build_chapter_bundle(
            chapter_dir=chapter_dir,
            output_dir=output_dir,
            version=version,
            scope_id=scope_id_override,
            bundle_name=f"{chapter_dir.name}_{version}.tar.gz",
        )
    except Exception as e:
        print(f"  [BUILD FAILED] {e}", file=sys.stderr)
        return False

    scope_id = manifest["scope_id"]
    title = manifest["chapter"]["title"]
    print(f"  scope_id : {scope_id}")
    print(f"  title    : {title}")
    print(f"  files    : {len(manifest['files'])}")
    print(f"  bundle   : {bundle_path}")

    if dry_run:
        print("  [dry-run] Skipping upload.")
        return True

    try:
        result = _upload(server, admin_key, bundle_path, scope_id, version)
        print(f"  Uploaded  id={result.get('id')}")
        print(f"  URL: {result.get('artifact_url')}")
    except Exception as e:
        print(f"  [UPLOAD FAILED] {e}", file=sys.stderr)
        return False
    finally:
        if not keep_bundle and bundle_path.exists():
            bundle_path.unlink()

    return True


def main() -> int:
    args = parse_args()

    version = _auto_version() if args.auto_version else args.version
    print(f"Version: {version}")

    # Collect chapter directories
    if args.chapter_dir:
        chapter_dirs = [args.chapter_dir.resolve()]
    else:
        course_dir = args.course_dir.resolve()
        chapters_root = course_dir / "chapters"
        if not chapters_root.is_dir():
            print(f"Error: no chapters/ directory in {course_dir}", file=sys.stderr)
            return 1
        chapter_dirs = sorted(
            d for d in chapters_root.iterdir() if d.is_dir() and (d / "chapter.json").exists()
        )
        if not chapter_dirs:
            print(f"Error: no chapter.json files found under {chapters_root}", file=sys.stderr)
            return 1
        print(f"Found {len(chapter_dirs)} chapter(s) in {course_dir.name}")

    success = 0
    failed = 0
    with tempfile.TemporaryDirectory(prefix="chapter-upload-") as tmpdir:
        output_dir = Path(tmpdir)
        for chapter_dir in chapter_dirs:
            ok = build_and_upload_one(
                chapter_dir=chapter_dir,
                server=args.server,
                admin_key=args.admin_key,
                version=version,
                scope_id_override=args.scope_id,
                dry_run=args.dry_run,
                keep_bundle=args.keep_bundle,
                output_dir=output_dir,
            )
            if ok:
                success += 1
            else:
                failed += 1

    print(f"\nDone. {success} succeeded, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
