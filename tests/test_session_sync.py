"""Integration tests for cross-device session sync endpoints (Task 12 smoke test).

Run with:
    RUN_INTEGRATION=1 BASE_URL=http://<server>:10723 uv run pytest -q tests/test_session_sync.py
"""

from uuid import uuid4

import pytest


@pytest.mark.integration
def test_session_sync_flow(client, integration_enabled: bool):
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1 to execute integration tests")

    email = f"sync_test_{uuid4().hex[:8]}@example.com"
    password = f"Pwd-{uuid4().hex[:10]}"
    device_id = f"dev-{uuid4().hex[:8]}"

    # ── Register ──────────────────────────────────────────────────────────────

    resp = client.post(
        "/v1/auth/request-email-code",
        json={"email": email, "purpose": "register"},
    )
    assert resp.status_code == 200, resp.text
    dev_code = resp.json().get("dev_code")
    if not dev_code:
        pytest.skip("No dev_code; run in development environment")

    resp = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "verification_code": dev_code,
            "password": password,
            "display_name": "Sync Tester",
            "device_id": device_id,
        },
    )
    assert resp.status_code == 201, resp.text
    access_token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    chapter_id = f"test_chapter_{uuid4().hex[:8]}"

    # ── 1. Session registration ────────────────────────────────────────────────

    resp = client.post(
        f"/v1/chapters/{chapter_id}/sessions",
        json={"course_id": None},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "session_id" in data
    assert "created_at" in data
    session_id = data["session_id"]
    assert len(session_id) > 0

    # ── 2. Turn append (idempotent) ────────────────────────────────────────────

    turn_payload = {
        "chapter_id": chapter_id,
        "turn_index": 0,
        "user_message": "Hello, what is pandas?",
        "companion_response": "Pandas is a data analysis library for Python.",
        "turn_outcome": {"understood": True},
    }
    resp = client.post(f"/v1/sessions/{session_id}/turns", json=turn_payload, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["accepted"] is True

    # Idempotency: posting same turn_index again must not raise an error
    resp = client.post(f"/v1/sessions/{session_id}/turns", json=turn_payload, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["accepted"] is True

    # Second turn
    resp = client.post(
        f"/v1/sessions/{session_id}/turns",
        json={
            "chapter_id": chapter_id,
            "turn_index": 1,
            "user_message": "Show me an example.",
            "companion_response": "Sure! `import pandas as pd`",
            "turn_outcome": {},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # ── 3. Memory upsert ───────────────────────────────────────────────────────

    memory = {"memo_digest": {"topics_covered": ["pandas intro"]}, "memory_state": {}}
    resp = client.put(
        f"/v1/sessions/{session_id}/memory",
        json={"chapter_id": chapter_id, "memory_json": memory},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] is True

    # Upsert again (update path)
    memory2 = {"memo_digest": {"topics_covered": ["pandas intro", "dataframe"]}, "memory_state": {}}
    resp = client.put(
        f"/v1/sessions/{session_id}/memory",
        json={"chapter_id": chapter_id, "memory_json": memory2},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # ── 4. Report upsert ───────────────────────────────────────────────────────

    report_md = "# Dynamic Report\n\n**Progress:** Student understands pandas basics."
    resp = client.put(
        f"/v1/sessions/{session_id}/report",
        json={"chapter_id": chapter_id, "report_md": report_md},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] is True

    # Upsert again (update path)
    resp = client.put(
        f"/v1/sessions/{session_id}/report",
        json={"chapter_id": chapter_id, "report_md": report_md + "\n\nUpdated."},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # ── 5. Recovery fetch ──────────────────────────────────────────────────────

    resp = client.get(f"/v1/chapters/{chapter_id}/session-state", headers=headers)
    assert resp.status_code == 200, resp.text
    state = resp.json()
    assert state["has_data"] is True
    assert state["session_id"] == session_id
    assert len(state["turns"]) == 2
    assert state["turns"][0]["turn_index"] == 0
    assert state["turns"][0]["user_message"] == "Hello, what is pandas?"
    assert state["turns"][1]["turn_index"] == 1
    assert state["memory"] == memory2
    assert "Updated." in state["report_md"]

    # Unknown chapter → has_data: false
    resp = client.get(f"/v1/chapters/nonexistent_chapter_xyz/session-state", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_data"] is False

    # ── 6. Workspace file submit (upload-url + confirm + list) ─────────────────

    fake_size = 1024  # 1 KB
    resp = client.post(
        "/v1/storage/workspace/upload-url",
        json={"chapter_id": chapter_id, "filename": "solution.py", "file_size_bytes": fake_size},
        headers=headers,
    )
    # May be 200 (OSS disabled → dev fallback) or 200 with real presigned URL
    assert resp.status_code == 200, resp.text
    url_data = resp.json()
    assert "presigned_url" in url_data
    assert "oss_key" in url_data
    oss_key = url_data["oss_key"]
    assert "solution.py" in oss_key

    # Confirm upload (skip actual OSS PUT since we can't upload to OSS in CI)
    resp = client.post(
        "/v1/storage/workspace/confirm",
        json={
            "oss_key": oss_key,
            "filename": "solution.py",
            "chapter_id": chapter_id,
            "file_size_bytes": fake_size,
            "session_id": session_id,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    quota = resp.json()
    assert quota["quota_used_bytes"] >= fake_size
    assert quota["quota_limit_bytes"] == 100 * 1024 * 1024

    # List files
    resp = client.get("/v1/storage/workspace/files", headers=headers)
    assert resp.status_code == 200, resp.text
    files_data = resp.json()
    assert "files" in files_data
    assert len(files_data["files"]) >= 1
    filenames = [f["filename"] for f in files_data["files"]]
    assert "solution.py" in filenames

    # ── 7. Access control: wrong user cannot access session ────────────────────

    # Register a second user
    email2 = f"sync_other_{uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/v1/auth/request-email-code",
        json={"email": email2, "purpose": "register"},
    )
    assert resp.status_code == 200
    dev_code2 = resp.json().get("dev_code")
    if dev_code2:
        resp = client.post(
            "/v1/auth/register",
            json={
                "email": email2,
                "verification_code": dev_code2,
                "password": f"Pwd-{uuid4().hex[:10]}",
                "display_name": "Other User",
                "device_id": f"dev-{uuid4().hex[:8]}",
            },
        )
        if resp.status_code == 201:
            other_token = resp.json()["access_token"]
            other_headers = {"Authorization": f"Bearer {other_token}"}

            # Should get 403 or 404 when accessing another user's session
            resp = client.post(
                f"/v1/sessions/{session_id}/turns",
                json={
                    "chapter_id": chapter_id,
                    "turn_index": 99,
                    "user_message": "unauthorized",
                    "companion_response": "should fail",
                    "turn_outcome": {},
                },
                headers=other_headers,
            )
            assert resp.status_code in (403, 404), f"Expected 403/404 but got {resp.status_code}"
