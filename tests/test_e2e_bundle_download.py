"""
E2E integration tests: full bundle download loop against the live backend.

Tests the complete flow:
  check-chapter/check-app → artifact_url → resolve URL → download → verify sha256

Requires:
  - RUN_INTEGRATION=1
  - BASE_URL pointing to a running backend with real bundles registered
  - Test student enrolled in SOC101 (created by seed data)
"""
from __future__ import annotations

import hashlib
import os

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://localhost:10723")
TEST_EMAIL = os.getenv("TEST_EMAIL", "student@example.com")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "StrongPass123")
COURSE_ID = os.getenv("COURSE_ID", "a2159fb9-5973-4cda-be1c-59a190a91d10")
CHAPTER_ID = os.getenv("CHAPTER_ID", "ch1_intro")


def _login() -> str:
    resp = httpx.post(
        f"{BASE_URL}/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "device_id": "e2e-download-test"},
        timeout=10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _download_and_verify(download_url: str, expected_sha256: str) -> int:
    """Download a bundle and verify its sha256. Returns size in bytes."""
    dl = httpx.get(download_url, follow_redirects=True, timeout=60)
    assert dl.status_code == 200, f"Download failed ({dl.status_code}): {dl.text[:200]}"
    assert dl.content[:2] == b"\x1f\x8b", "Downloaded file is not a valid gzip"
    if expected_sha256:
        actual = hashlib.sha256(dl.content).hexdigest()
        assert actual == expected_sha256, f"SHA256 mismatch: got {actual}, expected {expected_sha256}"
    return len(dl.content)


@pytest.mark.integration
def test_chapter_bundle_full_download_loop(integration_enabled: bool) -> None:
    """check-chapter → artifact_url → resolve → download → verify sha256."""
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1")

    token = _login()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. check-chapter with nothing installed
    check = httpx.post(
        f"{BASE_URL}/v1/updates/check-chapter",
        headers=headers,
        json={
            "course_id": COURSE_ID,
            "chapter_id": CHAPTER_ID,
            "installed": {"chapter_bundle": None, "experts": {}},
        },
        timeout=10,
    )
    assert check.status_code == 200, check.text
    required = check.json()["required"]
    chapter_bundles = [b for b in required if b["bundle_type"] == "chapter"]
    if not chapter_bundles:
        pytest.skip(
            f"No chapter bundle in required for {COURSE_ID}/{CHAPTER_ID} "
            "— ensure seed data is loaded or set COURSE_ID/CHAPTER_ID"
        )

    bundle = chapter_bundles[0]
    artifact_url = bundle["artifact_url"]
    expected_sha = bundle.get("sha256", "")
    assert artifact_url, "artifact_url is empty"

    # 2. resolve artifact URL (passthrough if already http, signed if OSS key)
    resolve = httpx.post(
        f"{BASE_URL}/v1/oss/resolve-artifact-url",
        headers=headers,
        json={"artifact": artifact_url, "expires_seconds": 120},
        timeout=10,
    )
    assert resolve.status_code == 200, resolve.text
    download_url = resolve.json()["artifact_url"]
    assert download_url.startswith("http"), f"Resolved URL is not http: {download_url!r}"

    # 3. Download and verify
    size = _download_and_verify(download_url, expected_sha)
    assert size > 0, "Downloaded file is empty"


@pytest.mark.integration
def test_sidecar_bundle_full_download_loop(integration_enabled: bool) -> None:
    """check-app with no python_runtime → resolve → download → verify."""
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1")

    token = _login()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. check-app with no installed bundles, platform_scope=dev-local
    check = httpx.post(
        f"{BASE_URL}/v1/updates/check-app",
        headers=headers,
        json={
            "installed": {"app_agents": "", "experts_shared": "", "python_runtime": ""},
            "platform_scope": "dev-local",
        },
        timeout=10,
    )
    assert check.status_code == 200, check.text
    payload = check.json()
    all_bundles = payload.get("required", []) + payload.get("optional", [])
    pr = next((b for b in all_bundles if b["bundle_type"] == "python_runtime"), None)
    assert pr is not None, f"No python_runtime bundle in check-app response: {all_bundles}"

    # 2. resolve artifact URL
    resolve = httpx.post(
        f"{BASE_URL}/v1/oss/resolve-artifact-url",
        headers=headers,
        json={"artifact": pr["artifact_url"], "expires_seconds": 120},
        timeout=10,
    )
    assert resolve.status_code == 200, resolve.text
    download_url = resolve.json()["artifact_url"]
    assert download_url.startswith("http"), f"Resolved URL is not http: {download_url!r}"

    # 3. Download and verify
    expected_sha = pr.get("sha256", "")
    size = _download_and_verify(download_url, expected_sha)
    assert size > 0, "Downloaded file is empty"
