from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import BundleRelease
from app.schemas.admin_bundles import BundlePublishRequest
from app.services.oss import oss_service


def _raise_conflict() -> None:
    raise ApiError(status_code=409, code="BUNDLE_RELEASE_CONFLICT", message="Bundle release already exists")


def publish_bundle(db: Session, request: BundlePublishRequest) -> BundleRelease:
    exists = db.execute(
        select(BundleRelease.id).where(
            BundleRelease.bundle_type == request.bundle_type,
            BundleRelease.scope_id == request.scope_id,
            BundleRelease.version == request.version,
        )
    ).scalar_one_or_none()
    if exists is not None:
        _raise_conflict()

    release = BundleRelease(
        bundle_type=request.bundle_type,
        scope_id=request.scope_id,
        version=request.version,
        artifact_url=request.artifact_url,
        sha256=request.sha256,
        size_bytes=request.size_bytes,
        is_mandatory=request.is_mandatory,
        manifest_json=request.manifest_json,
    )
    db.add(release)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _raise_conflict()

    db.refresh(release)
    return release


async def upload_and_publish(
    db: Session,
    *,
    file_content: bytes,
    bundle_type: str,
    scope_id: str,
    version: str,
    is_mandatory: bool = True,
    manifest_json: dict | None = None,
) -> BundleRelease:
    sha256 = hashlib.sha256(file_content).hexdigest()
    size_bytes = len(file_content)
    artifact_url: str | None = None
    request = BundlePublishRequest(
        bundle_type=bundle_type,
        scope_id=scope_id,
        version=version,
        artifact_url="__upload_pending__",
        sha256=sha256,
        size_bytes=size_bytes,
        is_mandatory=is_mandatory,
        manifest_json=manifest_json or {},
    )
    release = BundleRelease(
        bundle_type=request.bundle_type,
        scope_id=request.scope_id,
        version=request.version,
        artifact_url=request.artifact_url,
        sha256=request.sha256,
        size_bytes=request.size_bytes,
        is_mandatory=request.is_mandatory,
        manifest_json=request.manifest_json,
    )
    db.add(release)
    try:
        # Reserve (bundle_type, scope_id, version) first.
        db.flush()
    except IntegrityError:
        db.rollback()
        _raise_conflict()

    try:
        artifact_url = await oss_service.upload_bundle(
            file_content=file_content,
            bundle_type=bundle_type,
            scope_id=scope_id,
            version=version,
        )
    except Exception:
        db.rollback()
        raise

    release.artifact_url = artifact_url
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if artifact_url:
            await oss_service.delete_bundle_artifact(artifact_url)
        _raise_conflict()
    except Exception:
        db.rollback()
        raise

    db.refresh(release)
    return release


def list_bundles(
    db: Session,
    *,
    bundle_type: str | None = None,
    scope_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[BundleRelease], int]:
    base_stmt = select(BundleRelease)
    if bundle_type:
        base_stmt = base_stmt.where(BundleRelease.bundle_type == bundle_type)
    if scope_id:
        base_stmt = base_stmt.where(BundleRelease.scope_id == scope_id)

    total = db.execute(select(func.count()).select_from(base_stmt.subquery())).scalar_one()
    items = db.execute(base_stmt.order_by(BundleRelease.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return items, int(total)


def get_bundle(db: Session, bundle_id: UUID) -> BundleRelease:
    bundle = db.get(BundleRelease, bundle_id)
    if not bundle:
        raise ApiError(status_code=404, code="BUNDLE_RELEASE_NOT_FOUND", message="Bundle release not found")
    return bundle


def delete_bundle(db: Session, bundle_id: UUID) -> None:
    bundle = db.get(BundleRelease, bundle_id)
    if not bundle:
        raise ApiError(status_code=404, code="BUNDLE_RELEASE_NOT_FOUND", message="Bundle release not found")

    db.delete(bundle)
    db.commit()
