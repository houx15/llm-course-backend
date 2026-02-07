from datetime import datetime, timezone
from uuid import uuid4

import pytest


@pytest.mark.integration
def test_p0_core_flow(client, integration_enabled: bool):
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1 to execute integration tests")

    email = f"student_{uuid4().hex[:8]}@example.com"
    device_id = f"dev-{uuid4().hex[:8]}"

    # 1) request register code
    resp = client.post(
        "/v1/auth/request-email-code",
        json={"email": email, "purpose": "register"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    code = payload.get("dev_code")
    if not code:
        pytest.skip("No dev_code available; run test in development environment")

    # 2) register
    resp = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "verification_code": code,
            "display_name": "P0 Tester",
            "device_id": device_id,
        },
    )
    assert resp.status_code == 201, resp.text
    auth = resp.json()
    access_token = auth["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # 3) join course
    resp = client.post("/v1/courses/join", json={"course_code": "SOC101"}, headers=headers)
    assert resp.status_code == 200, resp.text
    course = resp.json()["course"]
    course_id = course["id"]

    # 4) list chapters
    resp = client.get(f"/v1/courses/{course_id}/chapters", headers=headers)
    assert resp.status_code == 200, resp.text
    chapters = resp.json()["chapters"]
    assert len(chapters) > 0
    chapter_code = chapters[0]["chapter_code"]

    # 5) check app updates
    resp = client.post(
        "/v1/updates/check-app",
        json={
            "desktop_version": "0.1.0",
            "sidecar_version": "0.1.0",
            "installed": {"app_agents": "0.0.0", "experts_shared": "0.0.0"},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "required" in resp.json()

    # 6) check chapter updates
    resp = client.post(
        "/v1/updates/check-chapter",
        json={
            "course_id": course_id,
            "chapter_id": chapter_code,
            "installed": {"chapter_bundle": "0.0.0", "experts": {}},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # 7) sync progress
    resp = client.post(
        "/v1/progress/chapter",
        json={
            "course_id": course_id,
            "chapter_id": chapter_code,
            "session_id": f"sess_{uuid4().hex[:8]}",
            "status": "IN_PROGRESS",
            "task_snapshot": {"current_task": "intro", "completed": []},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("accepted") is True

    # 8) ingest analytics
    resp = client.post(
        "/v1/analytics/events:ingest",
        json={
            "events": [
                {
                    "event_id": f"evt_{uuid4().hex[:12]}",
                    "event_type": "turn_completed",
                    "event_time": datetime.now(timezone.utc).isoformat(),
                    "course_id": course_id,
                    "chapter_id": chapter_code,
                    "session_id": f"sess_{uuid4().hex[:8]}",
                    "payload": {"turn": 1},
                }
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ingest = resp.json()
    assert ingest["accepted"] == 1
    assert ingest["failed"] == 0
