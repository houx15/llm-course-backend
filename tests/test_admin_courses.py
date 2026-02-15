import hashlib
import os
from uuid import uuid4

import pytest


ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


def _require_integration(integration_enabled: bool) -> None:
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1 to execute integration tests")


def _admin_headers() -> dict[str, str]:
    if not ADMIN_API_KEY:
        pytest.skip("Set ADMIN_API_KEY to run admin course integration tests")
    return {"X-Admin-Key": ADMIN_API_KEY}


def _register_and_login(client):
    email = f"admin_course_{uuid4().hex[:8]}@example.com"
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
            "display_name": "Admin Course Tester",
            "device_id": device_id,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    token = register_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_chapters_visible_only_after_bundle_and_intro_updates(client, integration_enabled: bool):
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()
    user_headers = _register_and_login(client)

    course_code = f"CS{uuid4().hex[:6]}".upper()
    create_course_resp = client.post(
        "/v1/admin/courses",
        headers=admin_headers,
        json={
            "course_code": course_code,
            "title": "Content Workflow Course",
            "description": "Testing staged release for chapters",
            "instructor": "Prof. Content",
            "semester": "Spring 2026",
            "chapters": [
                {
                    "chapter_code": "ch1_foundation",
                    "title": "Foundation",
                    "order": 1,
                    "intro_text": "Initial foundation intro",
                },
                {
                    "chapter_code": "ch2_methods",
                    "title": "Methods",
                    "order": 2,
                    "intro_text": "Initial methods intro",
                },
            ],
        },
    )
    assert create_course_resp.status_code == 201, create_course_resp.text
    course_payload = create_course_resp.json()
    course_id = course_payload["id"]

    join_resp = client.post("/v1/courses/join", json={"course_code": course_code}, headers=user_headers)
    assert join_resp.status_code == 200, join_resp.text

    chapters_before_bundle = client.get(f"/v1/courses/{course_id}/chapters", headers=user_headers)
    assert chapters_before_bundle.status_code == 200, chapters_before_bundle.text
    assert chapters_before_bundle.json()["chapters"] == []

    publish_version = f"1.0.{uuid4().hex[:4]}"
    chapter_scope = f"{course_id}/ch1_foundation"
    publish_resp = client.post(
        "/v1/admin/bundles/publish",
        headers=admin_headers,
        json={
            "bundle_type": "chapter",
            "scope_id": chapter_scope,
            "version": publish_version,
            "artifact_url": f"https://cdn.example.com/bundles/chapter/{chapter_scope}/{publish_version}/bundle.tar.gz",
            "sha256": hashlib.sha256(chapter_scope.encode("utf-8")).hexdigest(),
            "size_bytes": 87654,
            "is_mandatory": True,
            "manifest_json": {"required_experts": []},
        },
    )
    assert publish_resp.status_code == 201, publish_resp.text

    chapters_after_bundle = client.get(f"/v1/courses/{course_id}/chapters", headers=user_headers)
    assert chapters_after_bundle.status_code == 200, chapters_after_bundle.text
    chapters_payload = chapters_after_bundle.json()["chapters"]
    assert len(chapters_payload) == 1
    assert chapters_payload[0]["chapter_code"] == "ch1_foundation"
    assert chapters_payload[0]["intro_text"] == "Initial foundation intro"

    patch_intro_resp = client.patch(
        f"/v1/admin/courses/{course_id}/chapters/ch1_foundation/intro",
        headers=admin_headers,
        json={"intro_text": "Updated intro for chapter 1"},
    )
    assert patch_intro_resp.status_code == 200, patch_intro_resp.text
    assert patch_intro_resp.json()["intro_text"] == "Updated intro for chapter 1"

    admin_course_resp = client.get(f"/v1/admin/courses/{course_id}", headers=admin_headers)
    assert admin_course_resp.status_code == 200, admin_course_resp.text
    chapter_rows = admin_course_resp.json()["chapters"]
    row = next((item for item in chapter_rows if item["chapter_code"] == "ch1_foundation"), None)
    assert row is not None
    assert row["intro_text"] == "Updated intro for chapter 1"
    assert row["has_bundle"] is True
