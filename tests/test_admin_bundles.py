import hashlib
import gzip
import os
from uuid import uuid4

import pytest


ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


def _require_integration(integration_enabled: bool) -> None:
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1 to execute integration tests")


def _admin_headers() -> dict[str, str]:
    if not ADMIN_API_KEY:
        pytest.skip("Set ADMIN_API_KEY to run admin bundle integration tests")
    return {"X-Admin-Key": ADMIN_API_KEY}


def _register_and_login(client):
    email = f"admin_bundle_{uuid4().hex[:8]}@example.com"
    password = f"Pwd-{uuid4().hex[:10]}"
    device_id = f"dev-{uuid4().hex[:8]}"

    code_resp = client.post("/v1/auth/request-email-code", json={"email": email, "purpose": "register"})
    assert code_resp.status_code == 200, code_resp.text
    code = code_resp.json().get("dev_code")
    if not code:
        pytest.skip("No dev_code available; run tests in development mode")

    register_resp = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "verification_code": code,
            "password": password,
            "display_name": "Admin Bundle Tester",
            "device_id": device_id,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    token = register_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _gzip_payload(raw_bytes: bytes) -> bytes:
    return gzip.compress(raw_bytes)


def _enroll_and_get_course_chapter(client, user_headers: dict[str, str]) -> tuple[str, str]:
    join_resp = client.post("/v1/courses/join", json={"course_code": "SOC101"}, headers=user_headers)
    assert join_resp.status_code == 200, join_resp.text
    course_id = join_resp.json()["course"]["id"]

    chapters_resp = client.get(f"/v1/courses/{course_id}/chapters", headers=user_headers)
    assert chapters_resp.status_code == 200, chapters_resp.text
    chapter_code = chapters_resp.json()["chapters"][0]["chapter_code"]
    return course_id, chapter_code


@pytest.mark.integration
def test_admin_publish_duplicate_and_updates_visibility(client, integration_enabled: bool):
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()
    user_headers = _register_and_login(client)
    course_id, chapter_code = _enroll_and_get_course_chapter(client, user_headers)

    app_version = f"9.9.{uuid4().hex[:4]}"
    publish_payload = {
        "bundle_type": "app_agents",
        "scope_id": "core",
        "version": app_version,
        "artifact_url": f"https://cdn.example.com/bundles/app_agents/core/{app_version}/bundle.tar.gz",
        "sha256": hashlib.sha256(app_version.encode("utf-8")).hexdigest(),
        "size_bytes": 12345,
        "is_mandatory": True,
        "manifest_json": {},
    }

    publish_resp = client.post("/v1/admin/bundles/publish", json=publish_payload, headers=admin_headers)
    assert publish_resp.status_code == 201, publish_resp.text

    duplicate_resp = client.post("/v1/admin/bundles/publish", json=publish_payload, headers=admin_headers)
    assert duplicate_resp.status_code == 409, duplicate_resp.text

    check_app_resp = client.post(
        "/v1/updates/check-app",
        json={
            "desktop_version": "0.1.0",
            "sidecar_version": "0.1.0",
            "installed": {"app_agents": "0.0.1", "experts_shared": "0.0.1"},
        },
        headers=user_headers,
    )
    assert check_app_resp.status_code == 200, check_app_resp.text
    required = check_app_resp.json()["required"]
    assert any(item["bundle_type"] == "app_agents" and item["version"] == app_version for item in required)

    chapter_version = f"8.8.{uuid4().hex[:4]}"
    chapter_scope = f"{course_id}/{chapter_code}"
    chapter_publish_resp = client.post(
        "/v1/admin/bundles/publish",
        json={
            "bundle_type": "chapter",
            "scope_id": chapter_scope,
            "version": chapter_version,
            "artifact_url": f"https://cdn.example.com/bundles/chapter/{chapter_scope}/{chapter_version}/bundle.tar.gz",
            "sha256": hashlib.sha256(chapter_scope.encode("utf-8")).hexdigest(),
            "size_bytes": 23456,
            "is_mandatory": True,
            "manifest_json": {"required_experts": []},
        },
        headers=admin_headers,
    )
    assert chapter_publish_resp.status_code == 201, chapter_publish_resp.text

    check_chapter_resp = client.post(
        "/v1/updates/check-chapter",
        json={
            "course_id": course_id,
            "chapter_id": chapter_code,
            "installed": {"chapter_bundle": "0.0.1", "experts": {}},
        },
        headers=user_headers,
    )
    assert check_chapter_resp.status_code == 200, check_chapter_resp.text
    chapter_required = check_chapter_resp.json()["required"]
    assert any(item["bundle_type"] == "chapter" and item["version"] == chapter_version for item in chapter_required)


@pytest.mark.integration
def test_admin_list_filter_get_and_delete(client, integration_enabled: bool):
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()

    scope_id = f"data_inspector_{uuid4().hex[:8]}"
    version = f"1.2.{uuid4().hex[:4]}"
    publish_resp = client.post(
        "/v1/admin/bundles/publish",
        json={
            "bundle_type": "experts",
            "scope_id": scope_id,
            "version": version,
            "artifact_url": f"https://cdn.example.com/bundles/experts/{scope_id}/{version}/bundle.tar.gz",
            "sha256": hashlib.sha256(scope_id.encode("utf-8")).hexdigest(),
            "size_bytes": 34567,
            "is_mandatory": False,
            "manifest_json": {"platform": "darwin-arm64"},
        },
        headers=admin_headers,
    )
    assert publish_resp.status_code == 201, publish_resp.text
    bundle_id = publish_resp.json()["id"]

    list_resp = client.get(
        "/v1/admin/bundles",
        params={"bundle_type": "experts", "scope_id": scope_id, "limit": 20, "offset": 0},
        headers=admin_headers,
    )
    assert list_resp.status_code == 200, list_resp.text
    list_payload = list_resp.json()
    assert list_payload["total"] >= 1
    assert any(item["id"] == bundle_id for item in list_payload["bundles"])

    get_resp = client.get(f"/v1/admin/bundles/{bundle_id}", headers=admin_headers)
    assert get_resp.status_code == 200, get_resp.text
    get_payload = get_resp.json()
    assert get_payload["manifest_json"] == {"platform": "darwin-arm64"}

    delete_resp = client.delete(f"/v1/admin/bundles/{bundle_id}", headers=admin_headers)
    assert delete_resp.status_code == 204, delete_resp.text

    missing_resp = client.get(f"/v1/admin/bundles/{bundle_id}", headers=admin_headers)
    assert missing_resp.status_code == 404, missing_resp.text


@pytest.mark.integration
def test_admin_auth_missing_or_invalid_key(client, integration_enabled: bool):
    _require_integration(integration_enabled)

    missing_resp = client.get("/v1/admin/bundles")
    assert missing_resp.status_code == 403, missing_resp.text

    invalid_resp = client.get("/v1/admin/bundles", headers={"X-Admin-Key": "wrong-key"})
    assert invalid_resp.status_code == 403, invalid_resp.text


@pytest.mark.integration
def test_admin_upload_computes_sha256_and_size(client, integration_enabled: bool):
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()

    file_content = _gzip_payload(f"bundle-content-{uuid4().hex}".encode("utf-8"))
    expected_sha = hashlib.sha256(file_content).hexdigest()
    expected_size = len(file_content)
    scope_id = f"shared_{uuid4().hex[:8]}"
    version = f"3.0.{uuid4().hex[:4]}"

    upload_resp = client.post(
        "/v1/admin/bundles/upload",
        headers=admin_headers,
        data={
            "bundle_type": "experts_shared",
            "scope_id": scope_id,
            "version": version,
            "is_mandatory": "false",
        },
        files={"file": ("bundle.tar.gz", file_content, "application/gzip")},
    )
    assert upload_resp.status_code == 201, upload_resp.text
    bundle_id = upload_resp.json()["id"]

    get_resp = client.get(f"/v1/admin/bundles/{bundle_id}", headers=admin_headers)
    assert get_resp.status_code == 200, get_resp.text
    payload = get_resp.json()
    assert payload["sha256"] == expected_sha
    assert payload["size_bytes"] == expected_size


@pytest.mark.integration
def test_admin_upload_duplicate_does_not_overwrite_existing_artifact(client, integration_enabled: bool):
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()

    scope_id = f"dup_scope_{uuid4().hex[:8]}"
    version = f"4.0.{uuid4().hex[:4]}"
    first_content = _gzip_payload(f"first-{uuid4().hex}".encode("utf-8"))
    second_content = _gzip_payload(f"second-{uuid4().hex}".encode("utf-8"))
    first_sha = hashlib.sha256(first_content).hexdigest()

    first_upload = client.post(
        "/v1/admin/bundles/upload",
        headers=admin_headers,
        data={
            "bundle_type": "experts_shared",
            "scope_id": scope_id,
            "version": version,
            "is_mandatory": "true",
        },
        files={"file": ("bundle.tar.gz", first_content, "application/gzip")},
    )
    assert first_upload.status_code == 201, first_upload.text
    bundle_id = first_upload.json()["id"]

    second_upload = client.post(
        "/v1/admin/bundles/upload",
        headers=admin_headers,
        data={
            "bundle_type": "experts_shared",
            "scope_id": scope_id,
            "version": version,
            "is_mandatory": "true",
        },
        files={"file": ("bundle.tar.gz", second_content, "application/gzip")},
    )
    assert second_upload.status_code == 409, second_upload.text

    detail = client.get(f"/v1/admin/bundles/{bundle_id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["sha256"] == first_sha
    artifact_url = detail_payload["artifact_url"]

    if artifact_url.startswith("/"):
        artifact_resp = client.get(artifact_url)
        assert artifact_resp.status_code == 200, artifact_resp.text
        assert hashlib.sha256(artifact_resp.content).hexdigest() == first_sha


@pytest.mark.integration
def test_admin_upload_rejects_non_tar_gz(client, integration_enabled: bool):
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()

    invalid_resp = client.post(
        "/v1/admin/bundles/upload",
        headers=admin_headers,
        data={
            "bundle_type": "experts_shared",
            "scope_id": f"bad_file_{uuid4().hex[:8]}",
            "version": "1.0.0",
            "is_mandatory": "false",
        },
        files={"file": ("bundle.bin", b"not-gzip-data", "application/octet-stream")},
    )
    assert invalid_resp.status_code == 400, invalid_resp.text


@pytest.mark.integration
def test_resolve_local_artifact_returns_http_url(client, integration_enabled: bool):
    """When OSS is disabled, resolve-artifact-url must return a full http URL."""
    _require_integration(integration_enabled)
    user_headers = _register_and_login(client)
    resp = client.post(
        "/v1/oss/resolve-artifact-url",
        json={"artifact": "/uploads/chapter/test/1.0.0/bundle.tar.gz", "expires_seconds": 60},
        headers=user_headers,
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["artifact_url"]
    assert url.startswith("http://") or url.startswith("https://"), f"Not a full URL: {url!r}"


@pytest.mark.integration
def test_check_app_returns_python_runtime(client, integration_enabled: bool):
    """check-app must include python_runtime bundle when registered in DB."""
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()
    user_headers = _register_and_login(client)
    scope_id = f"py312-darwin-arm64-{uuid4().hex[:6]}"
    version = f"1.0.{uuid4().hex[:4]}"

    # Register a python_runtime bundle
    payload = {
        "bundle_type": "python_runtime",
        "scope_id": scope_id,
        "version": version,
        "artifact_url": f"https://cdn.example.com/bundles/python_runtime/{scope_id}/{version}/bundle.tar.gz",
        "sha256": hashlib.sha256(version.encode()).hexdigest(),
        "size_bytes": 50_000_000,
        "is_mandatory": True,
        "manifest_json": {"platform": "darwin-arm64"},
    }
    pub = client.post("/v1/admin/bundles/publish", json=payload, headers=admin_headers)
    assert pub.status_code == 201, pub.text

    # check-app with no installed python_runtime — should return it as required
    check = client.post(
        "/v1/updates/check-app",
        json={
            "platform_scope": scope_id,
            "installed": {"app_agents": "", "experts_shared": "", "python_runtime": ""},
        },
        headers=user_headers,
    )
    assert check.status_code == 200, check.text
    all_bundles = check.json().get("required", []) + check.json().get("optional", [])
    pr_bundles = [b for b in all_bundles if b["bundle_type"] == "python_runtime"]
    assert len(pr_bundles) >= 1, f"Expected python_runtime in check-app response, got: {all_bundles}"


@pytest.mark.integration
def test_upload_chapter_bundle_is_downloadable(client, integration_enabled: bool):
    """Upload a real chapter bundle and verify check-chapter returns a downloadable URL."""
    import json as _json
    import io as _io
    import tarfile as _tarfile
    import time as _time
    import httpx as _httpx

    _require_integration(integration_enabled)
    admin_headers = _admin_headers()
    user_headers = _register_and_login(client)
    course_id, chapter_code = _enroll_and_get_course_chapter(client, user_headers)
    scope_id = f"{course_id}/{chapter_code}"

    # Build a minimal valid chapter bundle in-memory
    buf = _io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tf:
        manifest_data = _json.dumps({
            "format_version": "bundle-v2",
            "bundle_type": "chapter",
            "scope_id": scope_id,
            "version": "99.0.0",
            "created_at": "2026-02-21T00:00:00Z",
            "chapter": {"course_id": course_id, "chapter_code": chapter_code, "title": "Test"},
            "files": [],
        }).encode()
        ti = _tarfile.TarInfo("bundle.manifest.json")
        ti.size = len(manifest_data)
        tf.addfile(ti, _io.BytesIO(manifest_data))
        for fname in ["prompts/chapter_context.md", "prompts/task_list.md", "prompts/task_completion_principles.md"]:
            content = f"# {fname}".encode()
            ti = _tarfile.TarInfo(fname)
            ti.size = len(content)
            tf.addfile(ti, _io.BytesIO(content))
    bundle_bytes = buf.getvalue()

    # Upload via admin API
    version = f"99.0.{int(_time.time()) % 10000}"
    upload_resp = client.post(
        "/v1/admin/bundles/upload",
        headers=admin_headers,
        files={"file": ("bundle.tar.gz", bundle_bytes, "application/gzip")},
        data={
            "bundle_type": "chapter",
            "scope_id": scope_id,
            "version": version,
            "is_mandatory": "true",
            "manifest_json": _json.dumps({"required_experts": []}),
        },
    )
    assert upload_resp.status_code == 201, upload_resp.text
    artifact_url = upload_resp.json()["artifact_url"]

    # Resolve the artifact URL
    resolve_resp = client.post(
        "/v1/oss/resolve-artifact-url",
        json={"artifact": artifact_url, "expires_seconds": 60},
        headers=user_headers,
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    download_url = resolve_resp.json()["artifact_url"]
    assert download_url.startswith("http"), f"Expected http URL, got: {download_url!r}"

    # Download the bundle
    dl = _httpx.get(download_url, follow_redirects=True, timeout=30)
    assert dl.status_code == 200, f"Download failed: {dl.status_code}"
    assert dl.content[:2] == b"\x1f\x8b", "Downloaded file is not gzip"
    actual_sha = hashlib.sha256(dl.content).hexdigest()
    expected_sha = hashlib.sha256(bundle_bytes).hexdigest()
    assert actual_sha == expected_sha, f"SHA256 mismatch: {actual_sha} != {expected_sha}"
