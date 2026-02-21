from pydantic import BaseModel


class CheckAppRequest(BaseModel):
    desktop_version: str = ""
    sidecar_version: str = ""
    platform_scope: str = ""
    installed: dict[str, str] = {}


class CheckChapterInstalled(BaseModel):
    chapter_bundle: str | None = None
    experts: dict[str, str] = {}


class CheckChapterRequest(BaseModel):
    course_id: str
    chapter_id: str
    installed: CheckChapterInstalled


class BundleDescriptor(BaseModel):
    bundle_type: str
    scope_id: str
    version: str
    artifact_url: str
    sha256: str
    size_bytes: int
    mandatory: bool


class CheckAppResponse(BaseModel):
    required: list[BundleDescriptor]
    optional: list[BundleDescriptor]


class CheckChapterResolved(BaseModel):
    course_id: str
    chapter_id: str
    required_experts: list[str]


class CheckChapterResponse(BaseModel):
    required: list[BundleDescriptor]
    resolved_chapter: CheckChapterResolved


class RuntimeConfigResponse(BaseModel):
    conda_installer_url: str
    pip_index_url: str
    conda_channels: list[str]
