"""
Alibaba Cloud OSS service helpers for bundle delivery.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
import uuid

from app.core.config import get_settings


class OSSService:
    """OSS service for URL resolving and temporary credential issuance."""

    def __init__(self) -> None:
        self._sts_client = None
        self._settings = get_settings()

    def is_enabled(self) -> bool:
        s = self._settings
        return bool(s.oss_enabled and s.oss_bucket_name and s.oss_endpoint)

    def _normalize_object_key(self, artifact: str) -> str | None:
        value = str(artifact or "").strip()
        if not value:
            return None

        if value.startswith("http://") or value.startswith("https://"):
            return None

        if value.startswith("oss://"):
            parsed = urlparse(value)
            key = parsed.path.lstrip("/")
            return key or None

        return value.lstrip("/")

    def _oss_origin_url(self, key: str) -> str:
        s = self._settings
        return f"https://{s.oss_bucket_name}.{s.oss_endpoint}/{key}"

    def _cdn_url(self, key: str) -> str:
        s = self._settings
        if s.oss_cdn_domain:
            return f"https://{s.oss_cdn_domain}/{key}"
        return self._oss_origin_url(key)

    def _build_bundle_object_key(self, bundle_type: str, scope_id: str, version: str) -> str:
        prefix = self._settings.oss_bundle_prefix.strip("/")
        scope_path = PurePosixPath(scope_id.lstrip("/"))
        if not scope_path.parts:
            raise ValueError("Invalid scope_id")
        if ".." in scope_path.parts:
            raise ValueError("Invalid scope_id")
        if "/" in bundle_type or "/" in version:
            raise ValueError("Invalid bundle path")

        if prefix:
            path = PurePosixPath(prefix) / bundle_type / scope_path / version / "bundle.tar.gz"
        else:
            path = PurePosixPath(bundle_type) / scope_path / version / "bundle.tar.gz"
        return str(path)

    async def upload_bundle(
        self,
        file_content: bytes,
        bundle_type: str,
        scope_id: str,
        version: str,
    ) -> str:
        """
        Upload bundle tar.gz to OSS and return object key.
        If OSS is disabled, store it under ./uploads and return a local static path.
        """
        key = self._build_bundle_object_key(bundle_type=bundle_type, scope_id=scope_id, version=version)

        if self.is_enabled():
            s = self._settings
            if not (s.oss_access_key_id and s.oss_access_key_secret):
                raise RuntimeError("OSS credentials are not configured")

            try:
                import oss2
            except Exception as exc:  # pragma: no cover - depends on optional package
                raise RuntimeError("oss2 is required for OSS upload") from exc

            auth = oss2.Auth(s.oss_access_key_id, s.oss_access_key_secret)
            bucket = oss2.Bucket(auth, f"https://{s.oss_endpoint}", s.oss_bucket_name)
            result = bucket.put_object(key, file_content)
            if not (200 <= int(getattr(result, "status", 500)) < 300):
                raise RuntimeError("Failed to upload bundle to OSS")
            return key

        local_path = Path("uploads") / key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(file_content)
        return f"/uploads/{key}"

    async def delete_bundle_artifact(self, artifact: str) -> None:
        """
        Best-effort deletion for cleanup paths.
        Accepts object key or local /uploads path.
        """
        value = str(artifact or "").strip()
        if not value:
            return

        key = value
        if value.startswith("/uploads/"):
            key = value[len("/uploads/") :]
        elif value.startswith("uploads/"):
            key = value[len("uploads/") :]

        if self.is_enabled():
            s = self._settings
            if not (s.oss_access_key_id and s.oss_access_key_secret):
                return
            try:
                import oss2
            except Exception:
                return
            try:
                auth = oss2.Auth(s.oss_access_key_id, s.oss_access_key_secret)
                bucket = oss2.Bucket(auth, f"https://{s.oss_endpoint}", s.oss_bucket_name)
                bucket.delete_object(key)
            except Exception:
                return
            return

        local_path = Path("uploads") / key
        try:
            if local_path.exists():
                local_path.unlink()
            # Best-effort prune empty folders under uploads/.
            parent = local_path.parent
            uploads_root = Path("uploads").resolve()
            while parent.exists() and parent != uploads_root:
                if any(parent.iterdir()):
                    break
                parent.rmdir()
                parent = parent.parent
        except Exception:
            return

    def resolve_download_url(self, artifact: str, expires_seconds: int | None = None) -> str:
        """
        Resolve an artifact reference to a downloadable URL.

        Rules:
        - absolute http(s) url: passthrough
        - oss://bucket/key or object key: convert to signed url or public cdn/origin url
        """
        raw = str(artifact or "").strip()
        if not raw:
            return raw

        if raw.startswith("http://") or raw.startswith("https://"):
            return raw

        # Local upload path (when OSS disabled): build full http URL using base_url
        if raw.startswith("/uploads/") or raw.startswith("uploads/"):
            base = self._settings.base_url.rstrip("/")
            if base:
                clean = raw if raw.startswith("/") else f"/{raw}"
                return f"{base}{clean}"
            return raw  # No base_url configured — return as-is

        key = self._normalize_object_key(raw)
        if not key:
            return raw

        if not self.is_enabled():
            return raw

        s = self._settings
        if s.oss_download_signed_url_enabled:
            signed = self._try_sign_download_url(key, expires_seconds or s.oss_download_url_expire_seconds)
            if signed:
                return signed

        return self._cdn_url(key)

    def _try_sign_download_url(self, key: str, expires_seconds: int) -> str | None:
        s = self._settings
        if not (s.oss_access_key_id and s.oss_access_key_secret and s.oss_bucket_name and s.oss_endpoint):
            return None

        try:
            import oss2
        except Exception:
            return None

        try:
            auth = oss2.Auth(s.oss_access_key_id, s.oss_access_key_secret)
            bucket = oss2.Bucket(auth, f"https://{s.oss_endpoint}", s.oss_bucket_name)
            return bucket.sign_url("GET", key, expires_seconds)
        except Exception:
            return None

    def _get_sts_client(self):
        if self._sts_client is not None:
            return self._sts_client

        s = self._settings
        if not (s.oss_access_key_id and s.oss_access_key_secret and s.oss_region_id):
            return None

        try:
            from alibabacloud_tea_openapi.models import Config
            from alibabacloud_sts20150401.client import Client as StsClient
        except Exception:
            return None

        config = Config(
            access_key_id=s.oss_access_key_id,
            access_key_secret=s.oss_access_key_secret,
            region_id=s.oss_region_id,
        )
        self._sts_client = StsClient(config)
        return self._sts_client

    async def get_sts_token(
        self,
        *,
        duration_seconds: int | None = None,
        allowed_prefixes: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """
        Issue STS token. If allowed_prefixes is set, policy is scoped to those prefixes.
        """
        s = self._settings
        if not s.oss_role_arn:
            return None

        sts_client = self._get_sts_client()
        if not sts_client:
            return None

        duration = duration_seconds or s.oss_sts_duration_seconds
        duration = max(900, min(3600, int(duration)))

        policy = None
        if allowed_prefixes:
            resources = [f"acs:oss:*:*:{s.oss_bucket_name}/{prefix.lstrip('/')}" for prefix in allowed_prefixes]
            policy = json.dumps(
                {
                    "Version": "1",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["oss:GetObject", "oss:ListObjects", "oss:HeadObject"],
                            "Resource": resources,
                        }
                    ],
                }
            )

        try:
            from alibabacloud_sts20150401 import models as sts_models

            request = sts_models.AssumeRoleRequest(
                role_arn=s.oss_role_arn,
                role_session_name=f"bundle_download_{uuid.uuid4().hex[:8]}",
                duration_seconds=duration,
                policy=policy,
            )
            response = sts_client.assume_role(request)
            credentials = response.body.credentials
            return {
                "access_key_id": credentials.access_key_id,
                "access_key_secret": credentials.access_key_secret,
                "security_token": credentials.security_token,
                "expiration": credentials.expiration,
            }
        except Exception:
            return None

    async def get_download_credentials(
        self,
        *,
        duration_seconds: int | None = None,
        allowed_prefixes: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Return scoped temporary credentials and OSS metadata for direct client download.
        """
        s = self._settings
        prefixes = allowed_prefixes or [s.oss_bundle_prefix]
        sts = await self.get_sts_token(duration_seconds=duration_seconds, allowed_prefixes=prefixes)
        return {
            "bucket": s.oss_bucket_name,
            "endpoint": s.oss_endpoint,
            "region": s.oss_region_id,
            "cdn_domain": s.oss_cdn_domain or None,
            "allowed_prefixes": prefixes,
            "access_key_id": sts.get("access_key_id") if sts else None,
            "access_key_secret": sts.get("access_key_secret") if sts else None,
            "security_token": sts.get("security_token") if sts else None,
            "expiration": sts.get("expiration") if sts else None,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }


oss_service = OSSService()
