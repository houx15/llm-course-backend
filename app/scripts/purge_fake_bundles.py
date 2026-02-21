"""Delete bundle_releases rows whose artifact_url is a placeholder (e.g. cdn.example.com).

Usage:
    uv run python app/scripts/purge_fake_bundles.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import BundleRelease

# Hostname fragments that identify placeholder/fake artifact URLs.
FAKE_HOSTS = [
    "cdn.example.com",
    "example.com",
]


def is_fake(url: str) -> bool:
    return any(host in url for host in FAKE_HOSTS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge fake bundle_releases rows.")
    parser.add_argument("--dry-run", action="store_true", help="Print rows without deleting.")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        targets = db.execute(select(BundleRelease)).scalars().all()
        targets = [r for r in targets if is_fake(r.artifact_url)]

        if not targets:
            print("No fake bundle_releases found.")
            return

        print(f"Found {len(targets)} fake record(s):")
        for r in targets:
            print(f"  [{r.bundle_type}/{r.scope_id}] v{r.version}  {r.artifact_url}")

        if args.dry_run:
            print("\nDry-run — nothing deleted.")
            return

        ids = [r.id for r in targets]
        db.execute(delete(BundleRelease).where(BundleRelease.id.in_(ids)))
        db.commit()
        print(f"\nDeleted {len(ids)} record(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
