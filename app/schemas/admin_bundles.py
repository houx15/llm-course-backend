from typing import Literal

from pydantic import BaseModel, Field

BundleType = Literal["chapter", "app_agents", "experts", "experts_shared", "python_runtime"]


class BundlePublishRequest(BaseModel):
    bundle_type: BundleType
    scope_id: str
    version: str
    artifact_url: str
    sha256: str
    size_bytes: int = Field(..., gt=0)
    is_mandatory: bool = True
    manifest_json: dict = Field(default_factory=dict)


class BundlePublishResponse(BaseModel):
    id: str
    bundle_type: str
    scope_id: str
    version: str
    artifact_url: str
    created_at: str


class BundleDetailResponse(BundlePublishResponse):
    sha256: str
    size_bytes: int
    is_mandatory: bool
    manifest_json: dict


class BundleListResponse(BaseModel):
    bundles: list[BundlePublishResponse]
    total: int


class BundleUploadResponse(BaseModel):
    artifact_url: str
    sha256: str
    size_bytes: int
