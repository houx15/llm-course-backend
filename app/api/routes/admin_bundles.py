from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.admin_auth import require_admin_key
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import BundleRelease
from app.schemas.admin_bundles import (
    BundleDetailResponse,
    BundleListResponse,
    BundlePublishRequest,
    BundlePublishResponse,
    BundleType,
)
from app.services.bundle_publish_service import delete_bundle, get_bundle, list_bundles, publish_bundle, upload_and_publish

router = APIRouter(prefix="/v1/admin/bundles", tags=["admin"])


def _to_publish_response(release: BundleRelease) -> BundlePublishResponse:
    return BundlePublishResponse(
        id=str(release.id),
        bundle_type=release.bundle_type,
        scope_id=release.scope_id,
        version=release.version,
        artifact_url=release.artifact_url,
        created_at=release.created_at.isoformat(),
    )


def _to_detail_response(release: BundleRelease) -> BundleDetailResponse:
    return BundleDetailResponse(
        id=str(release.id),
        bundle_type=release.bundle_type,
        scope_id=release.scope_id,
        version=release.version,
        artifact_url=release.artifact_url,
        sha256=release.sha256,
        size_bytes=release.size_bytes,
        is_mandatory=release.is_mandatory,
        manifest_json=release.manifest_json,
        created_at=release.created_at.isoformat(),
    )


@router.post(
    "/publish",
    response_model=BundlePublishResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_key)],
)
def publish_bundle_release(
    payload: BundlePublishRequest,
    db: Session = Depends(get_db),
) -> BundlePublishResponse:
    release = publish_bundle(db, payload)
    return _to_publish_response(release)


@router.post(
    "/upload",
    response_model=BundlePublishResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_key)],
)
async def upload_bundle_release(
    file: UploadFile = File(...),
    bundle_type: BundleType = Form(...),
    scope_id: str = Form(...),
    version: str = Form(...),
    is_mandatory: bool = Form(True),
    manifest_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> BundlePublishResponse:
    filename = (file.filename or "").lower()
    if not filename.endswith(".tar.gz"):
        raise ApiError(
            status_code=400,
            code="INVALID_FILE_TYPE",
            message="Bundle file must use .tar.gz extension",
        )

    file_content = await file.read()
    if not file_content:
        raise ApiError(status_code=400, code="INVALID_FILE", message="Uploaded file is empty")
    if len(file_content) < 2 or file_content[:2] != b"\x1f\x8b":
        raise ApiError(
            status_code=400,
            code="INVALID_FILE_TYPE",
            message="Bundle file must be gzip-compressed (.tar.gz)",
        )

    manifest: dict = {}
    if manifest_json:
        try:
            parsed = json.loads(manifest_json)
        except json.JSONDecodeError as exc:
            raise ApiError(status_code=400, code="INVALID_MANIFEST", message="manifest_json must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ApiError(status_code=400, code="INVALID_MANIFEST", message="manifest_json must be a JSON object")
        manifest = parsed

    try:
        release = await upload_and_publish(
            db,
            file_content=file_content,
            bundle_type=bundle_type,
            scope_id=scope_id,
            version=version,
            is_mandatory=is_mandatory,
            manifest_json=manifest,
        )
    except ValueError as exc:
        raise ApiError(status_code=400, code="INVALID_BUNDLE_PATH", message=str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(status_code=503, code=ErrorCode.SERVER_MISCONFIGURED, message=str(exc)) from exc
    return _to_publish_response(release)


@router.get(
    "",
    response_model=BundleListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_bundle_releases(
    bundle_type: BundleType | None = Query(default=None),
    scope_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> BundleListResponse:
    releases, total = list_bundles(db, bundle_type=bundle_type, scope_id=scope_id, limit=limit, offset=offset)
    return BundleListResponse(bundles=[_to_publish_response(item) for item in releases], total=total)


@router.get(
    "/{bundle_id}",
    response_model=BundleDetailResponse,
    dependencies=[Depends(require_admin_key)],
)
def get_bundle_release(
    bundle_id: UUID,
    db: Session = Depends(get_db),
) -> BundleDetailResponse:
    return _to_detail_response(get_bundle(db, bundle_id))


@router.delete(
    "/{bundle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_key)],
)
def delete_bundle_release(
    bundle_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    delete_bundle(db, bundle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
