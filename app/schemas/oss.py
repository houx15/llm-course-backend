from pydantic import BaseModel, Field


class DownloadCredentialsRequest(BaseModel):
    duration_seconds: int | None = Field(default=None, ge=900, le=3600)
    allowed_prefixes: list[str] | None = None


class DownloadCredentialsResponse(BaseModel):
    bucket: str
    endpoint: str
    region: str
    cdn_domain: str | None = None
    allowed_prefixes: list[str]
    access_key_id: str | None = None
    access_key_secret: str | None = None
    security_token: str | None = None
    expiration: str | None = None
    issued_at: str


class ResolveArtifactUrlRequest(BaseModel):
    artifact: str
    expires_seconds: int | None = Field(default=None, ge=60, le=3600)


class ResolveArtifactUrlResponse(BaseModel):
    artifact_url: str
