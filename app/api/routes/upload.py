from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import ApiError
from app.schemas.oss import (
    DownloadCredentialsRequest,
    DownloadCredentialsResponse,
    ResolveArtifactUrlRequest,
    ResolveArtifactUrlResponse,
)
from app.services.oss import oss_service

router = APIRouter(prefix="/v1/oss", tags=["oss"])


@router.post("/download-credentials", response_model=DownloadCredentialsResponse)
async def get_download_credentials(
    payload: DownloadCredentialsRequest,
    current_user: CurrentUser,
) -> DownloadCredentialsResponse:
    del current_user

    if not oss_service.is_enabled():
        raise ApiError(
            status_code=503,
            code=ErrorCode.SERVER_MISCONFIGURED,
            message="OSS is not enabled",
        )

    credentials = await oss_service.get_download_credentials(
        duration_seconds=payload.duration_seconds,
        allowed_prefixes=payload.allowed_prefixes,
    )

    return DownloadCredentialsResponse(**credentials)


@router.post("/resolve-artifact-url", response_model=ResolveArtifactUrlResponse)
async def resolve_artifact_url(
    payload: ResolveArtifactUrlRequest,
    current_user: CurrentUser,
) -> ResolveArtifactUrlResponse:
    del current_user

    url = oss_service.resolve_download_url(
        payload.artifact,
        expires_seconds=payload.expires_seconds,
    )
    return ResolveArtifactUrlResponse(artifact_url=url)
