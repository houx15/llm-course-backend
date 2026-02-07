from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BundleRelease
from app.schemas.updates import BundleDescriptor


def to_bundle_descriptor(release: BundleRelease) -> BundleDescriptor:
    return BundleDescriptor(
        bundle_type=release.bundle_type,
        scope_id=release.scope_id,
        version=release.version,
        artifact_url=release.artifact_url,
        sha256=release.sha256,
        size_bytes=release.size_bytes,
        mandatory=release.is_mandatory,
    )


def latest_bundle_release(db: Session, bundle_type: str, scope_id: str | None = None) -> BundleRelease | None:
    stmt = select(BundleRelease).where(BundleRelease.bundle_type == bundle_type)
    if scope_id is not None:
        stmt = stmt.where(BundleRelease.scope_id == scope_id)
    stmt = stmt.order_by(BundleRelease.created_at.desc())
    return db.execute(stmt).scalars().first()


def check_bundle_required(installed_version: str | None, release: BundleRelease | None) -> BundleDescriptor | None:
    if not release:
        return None
    if installed_version == release.version:
        return None
    return to_bundle_descriptor(release)
