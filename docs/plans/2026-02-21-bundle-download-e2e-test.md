# Bundle Download & Sidecar Interaction E2E Test Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify that a registered/enrolled student can download real sidecar and chapter bundles from the backend, and that the sidecar uses the chapter bundle content to drive agent interaction.

**Architecture:** Three-phase: (1) fix backend so locally-uploaded bundles produce real downloadable http URLs, (2) build and upload real bundles, (3) write tests that walk the full download + sidecar interaction loop.

**Tech Stack:** Python/FastAPI (backend + sidecar), TypeScript/Electron (desktop), pytest integration tests, curl for manual verification.

---

## Context & Current State

| What | Status |
|------|--------|
| Backend running at `47.93.151.131:10723`, admin key `12askd0e8712nkjzs9wfn1` | ✅ Running |
| Test student `student@example.com` / `StrongPass123` enrolled in SOC101 | ✅ Done |
| Course `a2159fb9-5973-4cda-be1c-59a190a91d10`, chapter `ch1_intro` | ✅ In DB |
| Admin bundle upload API (`POST /v1/admin/bundles/upload`) stores to `./uploads/` when OSS disabled | ✅ Exists |
| Seed chapter bundle record exists but has **fake** `cdn.example.com` URL | ❌ Broken |
| `build_chapter_bundle.py` script in `llm-course-sidecar/scripts/` | ✅ Exists |
| Chapter content at `content/curriculum/course3_LLM_social_science/ch1_intro_python_LLM/` (3 required files) | ✅ Exists |
| `resolve_download_url()` returns `/uploads/...` path (not http) when OSS disabled | ❌ **BUG** |
| `check-app` endpoint does NOT return `python_runtime` bundle type | ❌ Missing |
| Desktop has `SidecarDownloadProgress.tsx`, `updateManager.ts` with `python_runtime` support | ✅ Exists |

---

## Phase 1 — Fix Backend: Local Uploads Must Return Full http URLs

**Problem:** When OSS is disabled, `upload_bundle()` stores the file and returns `/uploads/{key}`. The desktop calls `/v1/oss/resolve-artifact-url` which returns this path as-is (not `http://...`), then rejects it. Need a `BASE_URL` config so local paths become `http://host:port/uploads/...`.

### Task 1: Add BASE_URL to backend config

**Files:**
- Modify: `llm-course-backend/app/core/config.py`

**Step 1: Write failing test**

In `llm-course-backend/tests/test_admin_bundles.py`, add at the top of the file after existing imports:

```python
def test_resolve_local_artifact_returns_http_url(client, integration_enabled):
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
```

**Step 2: Run to verify failure**

```bash
cd llm-course-backend
RUN_INTEGRATION=1 BASE_URL=http://47.93.151.131:10723 ADMIN_API_KEY=12askd0e8712nkjzs9wfn1 \
  uv run pytest -q tests/test_admin_bundles.py::test_resolve_local_artifact_returns_http_url -v
```
Expected: FAIL — `url` will be `/uploads/...` which doesn't start with http

**Step 3: Add `base_url` to Settings**

In `llm-course-backend/app/core/config.py`, add inside `class Settings`:
```python
base_url: str = ""          # e.g. "http://47.93.151.131:10723" — used to build absolute URLs for local uploads
```

**Step 4: Fix `resolve_download_url` in OSS service**

In `llm-course-backend/app/services/oss.py`, update `resolve_download_url()`. After `if not self.is_enabled():` block, add handling for local `/uploads/` paths:

```python
def resolve_download_url(self, artifact: str, expires_seconds: int | None = None) -> str:
    raw = str(artifact or "").strip()
    if not raw:
        return raw

    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    # Local upload path (OSS disabled): build full http URL using BASE_URL
    if raw.startswith("/uploads/") or raw.startswith("uploads/"):
        base = self._settings.base_url.rstrip("/")
        if base:
            clean = raw if raw.startswith("/") else f"/{raw}"
            return f"{base}{clean}"
        return raw  # No BASE_URL configured — caller will fail, needs config

    key = self._normalize_object_key(raw)
    if not key:
        return raw

    if not self.is_enabled():
        return raw

    # ... rest of existing signed URL / CDN URL logic
```

**Step 5: Run test to verify it passes**

```bash
RUN_INTEGRATION=1 BASE_URL=http://47.93.151.131:10723 ADMIN_API_KEY=12askd0e8712nkjzs9wfn1 \
  uv run pytest -q tests/test_admin_bundles.py::test_resolve_local_artifact_returns_http_url -v
```
Expected: PASS

**Step 6: Set BASE_URL on the server**

SSH into the server (or update the running `.env`):
```bash
# In the backend .env on the server, add:
BASE_URL=http://47.93.151.131:10723
```
Then restart the backend: `docker compose restart api` (or equivalent).

**Step 7: Commit**

```bash
cd llm-course-backend
git add app/core/config.py app/services/oss.py tests/test_admin_bundles.py
git commit -m "fix: resolve local /uploads/ paths to full http URL when OSS disabled"
```

---

### Task 2: Add `python_runtime` to check-app response

**Problem:** `check-app` only returns `app_agents` and `experts_shared`. The desktop's `sidecar:ensureReady` needs `python_runtime` in the response to trigger the sidecar download.

**Files:**
- Modify: `llm-course-backend/app/api/routes/updates.py`
- Modify: `llm-course-backend/app/schemas/updates.py` (add `python_runtime` to installed schema if missing)

**Step 1: Write failing test**

In `llm-course-backend/tests/test_admin_bundles.py`:

```python
def test_check_app_returns_python_runtime(client, integration_enabled):
    """check-app must include python_runtime bundle when registered in DB."""
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()
    user_headers = _register_and_login(client)
    scope_id = f"py312-darwin-arm64-{uuid4().hex[:6]}"
    version = f"1.0.{uuid4().hex[:4]}"

    # Register a fake python_runtime bundle
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

    # check-app with no installed python_runtime
    check = client.post(
        "/v1/updates/check-app",
        json={"installed": {"app_agents": "", "experts_shared": "", "python_runtime": ""}},
        headers=user_headers,
    )
    assert check.status_code == 200, check.text
    all_bundles = check.json().get("required", []) + check.json().get("optional", [])
    pr_bundles = [b for b in all_bundles if b["bundle_type"] == "python_runtime"]
    assert len(pr_bundles) >= 1, f"Expected python_runtime in check-app response, got: {all_bundles}"
```

**Step 2: Run to verify failure**

```bash
RUN_INTEGRATION=1 BASE_URL=http://47.93.151.131:10723 ADMIN_API_KEY=12askd0e8712nkjzs9wfn1 \
  uv run pytest -q tests/test_admin_bundles.py::test_check_app_returns_python_runtime -v
```
Expected: FAIL — no `python_runtime` entries in response

**Step 3: Update CheckAppRequest schema**

In `llm-course-backend/app/schemas/updates.py`, ensure `installed` accepts `python_runtime`:
```python
class CheckAppRequest(BaseModel):
    desktop_version: str = ""
    sidecar_version: str = ""
    platform_scope: str = ""        # e.g. "py312-darwin-arm64"
    installed: dict[str, str] = {}  # bundle_type -> version string (already flexible)
```
(If `installed` is already `dict[str, str]` or similar, no change needed.)

**Step 4: Update check-app endpoint to include python_runtime**

In `llm-course-backend/app/api/routes/updates.py`, inside `check_app_updates()`:

```python
# After existing app_agents / experts_shared checks, add:

# Python runtime bundle (sidecar).
platform_scope = getattr(payload, 'platform_scope', '') or ''
# Try platform-specific first, then generic fallback scope IDs
pr_scope_ids = []
if platform_scope:
    pr_scope_ids.append(platform_scope)
pr_scope_ids.extend(["core", "default", "standard", "py312"])

pr_release = None
for scope in pr_scope_ids:
    pr_release = latest_bundle_release(db, bundle_type="python_runtime", scope_id=scope)
    if pr_release:
        break

pr_descriptor = check_bundle_required(payload.installed.get("python_runtime"), pr_release)
if pr_descriptor:
    required.append(pr_descriptor)
```

**Step 5: Run test to verify pass**

```bash
RUN_INTEGRATION=1 BASE_URL=http://47.93.151.131:10723 ADMIN_API_KEY=12askd0e8712nkjzs9wfn1 \
  uv run pytest -q tests/test_admin_bundles.py::test_check_app_returns_python_runtime -v
```
Expected: PASS

**Step 6: Commit**

```bash
git add app/api/routes/updates.py app/schemas/updates.py tests/test_admin_bundles.py
git commit -m "feat: include python_runtime bundle in check-app response"
```

---

## Phase 2 — Build & Upload Real Bundles

### Task 3: Build the chapter bundle for ch1_intro

**Files:**
- Use: `llm-course-sidecar/scripts/build_chapter_bundle.py`
- Source: `content/curriculum/course3_LLM_social_science/ch1_intro_python_LLM/`
- Output: `/tmp/ch1_intro_bundle.tar.gz`

**Step 1: Run the build script**

```bash
cd llm-course-sidecar
python scripts/build_chapter_bundle.py \
  --chapter-dir ../content/curriculum/course3_LLM_social_science/ch1_intro_python_LLM \
  --scope-id "a2159fb9-5973-4cda-be1c-59a190a91d10/ch1_intro" \
  --version "1.1.0" \
  --output /tmp/
```
Expected output: `Wrote /tmp/ch1_intro_bundle.tar.gz` and manifest summary showing 3 required prompt files.

**Step 2: Verify bundle structure**

```bash
python3 -c "
import tarfile, json
with tarfile.open('/tmp/ch1_intro_bundle.tar.gz', 'r:gz') as tf:
    names = tf.getnames()
    print('\n'.join(sorted(names)))
    m = tf.extractfile('bundle.manifest.json')
    if m:
        print('\n---MANIFEST---')
        print(json.loads(m.read()))
"
```
Expected: See `bundle.manifest.json`, `prompts/chapter_context.md`, `prompts/task_list.md`, `prompts/task_completion_principles.md`.

---

### Task 4: Upload chapter bundle and verify check-chapter returns real URL

**Files:**
- Test: `llm-course-backend/tests/test_admin_bundles.py`

**Step 1: Write the failing test first**

Add to `llm-course-backend/tests/test_admin_bundles.py`:

```python
import io

def test_upload_chapter_bundle_is_downloadable(client, integration_enabled):
    """Upload a real chapter bundle and verify check-chapter returns a downloadable URL."""
    _require_integration(integration_enabled)
    admin_headers = _admin_headers()
    user_headers = _register_and_login(client)
    course_id, chapter_code = _enroll_and_get_course_chapter(client, user_headers)
    scope_id = f"{course_id}/{chapter_code}"

    # Build a minimal valid chapter bundle in-memory
    import tarfile, io, json, time
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        manifest = json.dumps({
            "format_version": "bundle-v2",
            "bundle_type": "chapter",
            "scope_id": scope_id,
            "version": "2.0.0",
            "created_at": "2026-02-21T00:00:00Z",
            "chapter": {"course_id": course_id, "chapter_code": chapter_code, "title": "Test"},
            "files": [],
        }).encode()
        ti = tarfile.TarInfo("bundle.manifest.json")
        ti.size = len(manifest)
        tf.addfile(ti, io.BytesIO(manifest))
        for fname in ["prompts/chapter_context.md", "prompts/task_list.md", "prompts/task_completion_principles.md"]:
            content = f"# {fname}".encode()
            ti = tarfile.TarInfo(fname)
            ti.size = len(content)
            tf.addfile(ti, io.BytesIO(content))
    bundle_bytes = buf.getvalue()

    # Upload via admin API
    version = f"2.0.{int(time.time()) % 10000}"
    upload_resp = client.post(
        "/v1/admin/bundles/upload",
        headers=admin_headers,
        files={"file": ("bundle.tar.gz", bundle_bytes, "application/gzip")},
        data={
            "bundle_type": "chapter",
            "scope_id": scope_id,
            "version": version,
            "is_mandatory": "true",
            "manifest_json": json.dumps({"required_experts": []}),
        },
    )
    assert upload_resp.status_code == 201, upload_resp.text
    artifact_url = upload_resp.json()["artifact_url"]

    # Resolve the artifact URL via the OSS endpoint
    resolve_resp = client.post(
        "/v1/oss/resolve-artifact-url",
        json={"artifact": artifact_url, "expires_seconds": 60},
        headers=user_headers,
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    download_url = resolve_resp.json()["artifact_url"]
    assert download_url.startswith("http"), f"Expected http URL, got: {download_url!r}"

    # Download the bundle and verify it's a valid gzip
    import httpx
    dl = httpx.get(download_url, follow_redirects=True)
    assert dl.status_code == 200, f"Download failed: {dl.status_code} {dl.text[:200]}"
    assert dl.content[:2] == b"\x1f\x8b", "Downloaded file is not gzip"
    assert hashlib.sha256(dl.content).hexdigest() == upload_resp.json().get("sha256", ""), "SHA256 mismatch"
```

**Step 2: Run to verify failure** (fails because sha256 field may be missing or URL not http)

```bash
RUN_INTEGRATION=1 BASE_URL=http://47.93.151.131:10723 ADMIN_API_KEY=12askd0e8712nkjzs9wfn1 \
  uv run pytest -q tests/test_admin_bundles.py::test_upload_chapter_bundle_is_downloadable -v
```

**Step 3: If failing due to sha256 not in publish response**

Check `BundlePublishResponse` schema in `llm-course-backend/app/schemas/admin_bundles.py`. If sha256 is missing, add it and update `_to_publish_response()` in `admin_bundles.py`.

**Step 4: Run test until green**

Once Task 1 (BASE_URL fix) is deployed and sha256 is in response:
```bash
RUN_INTEGRATION=1 BASE_URL=http://47.93.151.131:10723 ADMIN_API_KEY=12askd0e8712nkjzs9wfn1 \
  uv run pytest -q tests/test_admin_bundles.py::test_upload_chapter_bundle_is_downloadable -v
```
Expected: PASS

**Step 5: Upload the real ch1_intro bundle to the running server**

```bash
# Delete existing fake chapter bundle first
BUNDLE_ID=$(curl -s -H "X-Admin-Key: 12askd0e8712nkjzs9wfn1" \
  "http://47.93.151.131:10723/v1/admin/bundles?bundle_type=chapter" \
  | python3 -c "import sys,json; bundles=json.load(sys.stdin)['bundles']; \
    [print(b['id']) for b in bundles if b['scope_id'].endswith('/ch1_intro')]")
echo "Deleting bundle: $BUNDLE_ID"
curl -X DELETE -H "X-Admin-Key: 12askd0e8712nkjzs9wfn1" \
  "http://47.93.151.131:10723/v1/admin/bundles/$BUNDLE_ID"

# Upload the real bundle built in Task 3
curl -X POST \
  -H "X-Admin-Key: 12askd0e8712nkjzs9wfn1" \
  -F "file=@/tmp/ch1_intro_bundle.tar.gz" \
  -F "bundle_type=chapter" \
  -F "scope_id=a2159fb9-5973-4cda-be1c-59a190a91d10/ch1_intro" \
  -F "version=1.1.0" \
  -F "is_mandatory=true" \
  -F 'manifest_json={"required_experts":["data_inspector","concept_explainer"]}' \
  "http://47.93.151.131:10723/v1/admin/bundles/upload" | python3 -m json.tool
```
Expected: 201 response with artifact_url starting with `/uploads/...`

**Step 6: Verify check-chapter now returns a real URL**

```bash
TOKEN=$(curl -s -X POST http://47.93.151.131:10723/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"student@example.com","password":"StrongPass123","device_id":"test-001"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s -X POST http://47.93.151.131:10723/v1/updates/check-chapter \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"course_id":"a2159fb9-5973-4cda-be1c-59a190a91d10","chapter_id":"ch1_intro","installed":{"chapter_bundle":null,"experts":{}}}' \
  | python3 -m json.tool
```
Expected: `artifact_url` is `/uploads/chapter/a2159fb9.../ch1_intro/1.1.0/bundle.tar.gz`

**Step 7: Resolve and download**

```bash
curl -s -X POST http://47.93.151.131:10723/v1/oss/resolve-artifact-url \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"artifact":"/uploads/chapter/a2159fb9-5973-4cda-be1c-59a190a91d10/ch1_intro/1.1.0/bundle.tar.gz","expires_seconds":60}' \
  | python3 -m json.tool
```
Expected: `artifact_url` is `http://47.93.151.131:10723/uploads/...`

```bash
DOWNLOAD_URL="http://47.93.151.131:10723/uploads/chapter/a2159fb9-5973-4cda-be1c-59a190a91d10/ch1_intro/1.1.0/bundle.tar.gz"
curl -o /tmp/downloaded_ch1.tar.gz "$DOWNLOAD_URL"
file /tmp/downloaded_ch1.tar.gz   # Should say "gzip compressed data"
```

**Step 8: Commit**

```bash
cd llm-course-backend
git add tests/test_admin_bundles.py
git commit -m "test: add upload+download integration test for chapter bundle"
```

---

### Task 5: Build and upload the sidecar (python_runtime) bundle

The `python_runtime` bundle is a packaged Python environment + sidecar code. For local testing, we create a **dev-mode bundle** — a thin tar.gz with a `runtime.manifest.json` that points to the system Python and the dev sidecar code already installed on the test machine.

**Step 1: Create the sidecar bundle packaging script**

Create `llm-course-sidecar/scripts/build_dev_sidecar_bundle.py`:

```python
#!/usr/bin/env python3
"""
Build a minimal dev-mode python_runtime bundle for testing the download/install flow.
This bundles the local sidecar source with a manifest pointing to the dev Python executable.
"""
import argparse, hashlib, json, os, subprocess, sys, tarfile, tempfile
from datetime import datetime, timezone
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar-src", required=True, help="Path to llm-course-sidecar directory")
    parser.add_argument("--python-path", default=sys.executable, help="Path to Python executable to embed in manifest")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--platform", default="dev-local")
    parser.add_argument("--output", default="/tmp/", help="Output directory")
    args = parser.parse_args()

    sidecar_src = Path(args.sidecar_src).resolve()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"sidecar_bundle_{args.version}.tar.gz"

    manifest = {
        "format_version": "bundle-v1",
        "bundle_type": "python_runtime",
        "scope_id": args.platform,
        "version": args.version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": {
            "executable_relpath": "start.sh",  # wrapper script
        },
        "sidecar": {
            "root_relpath": "sidecar_root",
        },
    }

    with tarfile.open(out_path, "w:gz") as tf:
        # Bundle manifest
        manifest_bytes = json.dumps(manifest, indent=2).encode()
        import io
        ti = tarfile.TarInfo("runtime.manifest.json")
        ti.size = len(manifest_bytes)
        tf.addfile(ti, io.BytesIO(manifest_bytes))

        # start.sh — wrapper that invokes the real system python
        python_path = Path(args.python_path).resolve()
        start_sh = f"#!/bin/sh\nexec '{python_path}' \"$@\"\n".encode()
        ti = tarfile.TarInfo("start.sh")
        ti.size = len(start_sh)
        ti.mode = 0o755
        tf.addfile(ti, io.BytesIO(start_sh))

        # sidecar_root/app/server/main.py — entry point the desktop looks for
        sidecar_main = b"""import sys, os
sidecar_src = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'src')
sys.path.insert(0, os.path.abspath(sidecar_src))
from sidecar.main import app
import uvicorn
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)
"""
        # Also add a symlink-style main.py that imports from installed sidecar
        for sub_path, content in [
            ("sidecar_root/app/__init__.py", b""),
            ("sidecar_root/app/server/__init__.py", b""),
            ("sidecar_root/app/server/main.py", sidecar_main),
        ]:
            ti = tarfile.TarInfo(sub_path)
            ti.size = len(content)
            tf.addfile(ti, io.BytesIO(content))

    print(f"Wrote: {out_path}")
    sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    size = out_path.stat().st_size
    print(f"SHA256: {sha256}")
    print(f"Size:   {size} bytes")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run the script to build the bundle**

```bash
cd llm-course-sidecar
python scripts/build_dev_sidecar_bundle.py \
  --sidecar-src . \
  --python-path $(which python3) \
  --version "0.1.0" \
  --platform "dev-local" \
  --output /tmp/
```
Expected: `/tmp/sidecar_bundle_0.1.0.tar.gz` with sha256 printed.

**Step 3: Upload to backend**

```bash
curl -X POST \
  -H "X-Admin-Key: 12askd0e8712nkjzs9wfn1" \
  -F "file=@/tmp/sidecar_bundle_0.1.0.tar.gz" \
  -F "bundle_type=python_runtime" \
  -F "scope_id=dev-local" \
  -F "version=0.1.0" \
  -F "is_mandatory=true" \
  -F 'manifest_json={"platform":"dev-local"}' \
  "http://47.93.151.131:10723/v1/admin/bundles/upload" | python3 -m json.tool
```

**Step 4: Verify check-app returns python_runtime**

```bash
TOKEN=<from login above>
curl -s -X POST http://47.93.151.131:10723/v1/updates/check-app \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"installed":{"app_agents":"","experts_shared":"","python_runtime":""},"platform_scope":"dev-local"}' \
  | python3 -m json.tool
```
Expected: response includes `python_runtime` bundle with `scope_id: "dev-local"`.

---

## Phase 3 — End-to-End Integration Tests

### Task 6: Integration test — full chapter bundle download loop

Write a single integration test that does the full loop: check-chapter → resolve URL → download → verify.

**File:** `llm-course-backend/tests/test_e2e_bundle_download.py`

**Step 1: Create the test file**

```python
"""
E2E integration test: chapter bundle download full loop.
Requires a real bundle registered in DB with a downloadable URL.
"""
import hashlib
import os
import pytest
import httpx


BASE_URL = os.getenv("BASE_URL", "http://47.93.151.131:10723")
TEST_EMAIL = os.getenv("TEST_EMAIL", "student@example.com")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "StrongPass123")
COURSE_ID = "a2159fb9-5973-4cda-be1c-59a190a91d10"
CHAPTER_ID = "ch1_intro"


@pytest.fixture
def auth_token():
    resp = httpx.post(f"{BASE_URL}/v1/auth/login", json={
        "email": TEST_EMAIL, "password": TEST_PASSWORD, "device_id": "e2e-test-001"
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.integration
def test_chapter_bundle_full_download_loop(auth_token, integration_enabled):
    """check-chapter → resolve URL → download → verify sha256."""
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1")

    headers = {"Authorization": f"Bearer {auth_token}"}

    # 1. check-chapter
    check = httpx.post(f"{BASE_URL}/v1/updates/check-chapter", headers=headers, json={
        "course_id": COURSE_ID,
        "chapter_id": CHAPTER_ID,
        "installed": {"chapter_bundle": None, "experts": {}},
    })
    assert check.status_code == 200, check.text
    required = check.json()["required"]
    chapter_bundles = [b for b in required if b["bundle_type"] == "chapter"]
    assert chapter_bundles, f"No chapter bundle in required: {required}"
    bundle = chapter_bundles[0]
    artifact_url = bundle["artifact_url"]
    expected_sha = bundle.get("sha256", "")
    print(f"  artifact_url = {artifact_url}")

    # 2. resolve URL
    resolve = httpx.post(f"{BASE_URL}/v1/oss/resolve-artifact-url", headers=headers,
                         json={"artifact": artifact_url, "expires_seconds": 120})
    assert resolve.status_code == 200, resolve.text
    download_url = resolve.json()["artifact_url"]
    assert download_url.startswith("http"), f"Not a full URL: {download_url!r}"
    print(f"  download_url = {download_url}")

    # 3. download
    dl = httpx.get(download_url, follow_redirects=True, timeout=60)
    assert dl.status_code == 200, f"Download failed ({dl.status_code})"
    assert dl.content[:2] == b"\x1f\x8b", "Not a gzip file"

    # 4. verify sha256
    if expected_sha:
        actual = hashlib.sha256(dl.content).hexdigest()
        assert actual == expected_sha, f"SHA256 mismatch: {actual} != {expected_sha}"

    print(f"  Downloaded {len(dl.content)} bytes, sha256 OK")


@pytest.mark.integration
def test_sidecar_bundle_full_download_loop(auth_token, integration_enabled):
    """check-app with no python_runtime → resolve URL → download."""
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1")

    headers = {"Authorization": f"Bearer {auth_token}"}

    check = httpx.post(f"{BASE_URL}/v1/updates/check-app", headers=headers, json={
        "installed": {"app_agents": "", "experts_shared": "", "python_runtime": ""},
        "platform_scope": "dev-local",
    })
    assert check.status_code == 200, check.text
    all_bundles = check.json().get("required", []) + check.json().get("optional", [])
    pr = next((b for b in all_bundles if b["bundle_type"] == "python_runtime"), None)
    assert pr, f"No python_runtime bundle in check-app response: {all_bundles}"

    resolve = httpx.post(f"{BASE_URL}/v1/oss/resolve-artifact-url", headers=headers,
                         json={"artifact": pr["artifact_url"], "expires_seconds": 120})
    assert resolve.status_code == 200
    download_url = resolve.json()["artifact_url"]
    assert download_url.startswith("http")

    dl = httpx.get(download_url, follow_redirects=True, timeout=120)
    assert dl.status_code == 200
    assert dl.content[:2] == b"\x1f\x8b"
    print(f"  Sidecar bundle: {len(dl.content)} bytes downloaded OK")
```

**Step 2: Run**

```bash
cd llm-course-backend
RUN_INTEGRATION=1 BASE_URL=http://47.93.151.131:10723 \
  uv run pytest -q tests/test_e2e_bundle_download.py -v
```
Expected: both tests PASS.

**Step 3: Commit**

```bash
git add tests/test_e2e_bundle_download.py
git commit -m "test: e2e bundle download loop for chapter and sidecar bundles"
```

---

### Task 7: Integration test — sidecar uses chapter bundle content for agent interaction

**File:** `llm-course-sidecar/tests/test_e2e_sidecar_interaction.py`

This test assumes the sidecar is running locally at `http://127.0.0.1:8000` with the chapter bundle available. It tests the full agent interaction loop.

**Step 1: Create the test file**

```python
"""
E2E test: sidecar loads chapter bundle and responds to student message via SSE.

Setup required:
  1. Build chapter bundle: python scripts/build_chapter_bundle.py --chapter-dir ...
  2. Start sidecar: uvicorn sidecar.main:app --host 127.0.0.1 --port 8000
     with CURRICULUM_DIR pointing to the extracted bundle OR the content dir

Environment:
  SIDECAR_URL=http://127.0.0.1:8000 (default)
  CHAPTER_BUNDLE_PATH=/tmp/ch1_intro_extracted  (extracted bundle root)
"""
import json
import os
import tarfile
import tempfile
import time
from pathlib import Path

import httpx
import pytest


SIDECAR_URL = os.getenv("SIDECAR_URL", "http://127.0.0.1:8000")
CHAPTER_BUNDLE_TAR = os.getenv("CHAPTER_BUNDLE_TAR", "/tmp/downloaded_ch1.tar.gz")
COURSE_ID = "a2159fb9-5973-4cda-be1c-59a190a91d10"
CHAPTER_ID = "ch1_intro"


def _sidecar_is_up() -> bool:
    try:
        r = httpx.get(f"{SIDECAR_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture
def extracted_bundle(tmp_path):
    """Extract the chapter bundle tar.gz to a temp dir."""
    bundle_tar = Path(CHAPTER_BUNDLE_TAR)
    if not bundle_tar.exists():
        pytest.skip(f"Chapter bundle not found at {CHAPTER_BUNDLE_TAR}. Run Task 4 first.")
    extract_dir = tmp_path / "bundle"
    extract_dir.mkdir()
    with tarfile.open(bundle_tar, "r:gz") as tf:
        tf.extractall(extract_dir)
    return extract_dir


@pytest.mark.integration
def test_sidecar_health(integration_enabled):
    """Sidecar must be running before other tests."""
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1")
    assert _sidecar_is_up(), f"Sidecar not running at {SIDECAR_URL}. Start it first."


@pytest.mark.integration
def test_sidecar_session_with_chapter_bundle(extracted_bundle, integration_enabled):
    """
    Full loop: create session → send message → receive SSE stream → verify done event.
    """
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION=1")

    if not _sidecar_is_up():
        pytest.skip("Sidecar not running")

    chapter_id = f"{COURSE_ID}/{CHAPTER_ID}"

    # 1. Create session
    create_resp = httpx.post(f"{SIDECAR_URL}/api/session/create", json={
        "chapter_id": chapter_id,
        "desktop_context": {
            "bundle_paths": {
                "chapter_bundle_path": str(extracted_bundle),
            }
        },
    }, timeout=30)
    assert create_resp.status_code == 200, create_resp.text
    session_id = create_resp.json()["session_id"]
    print(f"  Created session: {session_id}")

    # 2. Send student message
    send_resp = httpx.post(f"{SIDECAR_URL}/api/session/{session_id}/chat", json={
        "message": "I want to understand what we will learn in this chapter.",
    }, timeout=10)
    assert send_resp.status_code in (200, 202), send_resp.text

    # 3. Read SSE stream
    events = []
    with httpx.stream("GET", f"{SIDECAR_URL}/api/session/{session_id}/stream",
                      timeout=60, headers={"Accept": "text/event-stream"}) as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                raw = line[len("data: "):].strip()
                if raw and raw != "[DONE]":
                    try:
                        events.append(json.loads(raw))
                    except json.JSONDecodeError:
                        pass
            if any(e.get("type") == "done" for e in events):
                break

    # 4. Verify we got meaningful events
    event_types = [e.get("type") for e in events]
    print(f"  Received event types: {event_types}")
    assert "done" in event_types, f"No 'done' event. Got: {event_types}"

    # Check there's a companion reply
    companion_events = [e for e in events if e.get("type") == "message" and e.get("role") == "assistant"]
    assert companion_events, f"No assistant message in events: {events[:3]}"
    reply = companion_events[0].get("content", "")
    assert len(reply) > 20, f"Suspiciously short reply: {reply!r}"
    print(f"  Agent replied: {reply[:100]}...")
```

**Step 2: Start the sidecar with the downloaded chapter bundle**

```bash
cd llm-course-sidecar
# Extract the chapter bundle
mkdir -p /tmp/ch1_extracted
tar xzf /tmp/downloaded_ch1.tar.gz -C /tmp/ch1_extracted

# Start sidecar pointing to the extracted bundle directory
CHAPTER_BUNDLE_PATH=/tmp/ch1_extracted \
CURRICULUM_DIR=/tmp/ch1_extracted \
LLM_PROVIDER=anthropic \
LLM_API_KEY=<your-key> \
uvicorn sidecar.main:app --host 127.0.0.1 --port 8000 --reload
```

**Step 3: Run the test**

```bash
cd llm-course-sidecar
RUN_INTEGRATION=1 CHAPTER_BUNDLE_TAR=/tmp/downloaded_ch1.tar.gz \
  python -m pytest tests/test_e2e_sidecar_interaction.py -v -s
```
Expected: PASS — session created, SSE stream returns `done` event, companion message has content > 20 chars.

**Step 4: Commit**

```bash
cd llm-course-sidecar
git add tests/test_e2e_sidecar_interaction.py
git commit -m "test: e2e sidecar session with chapter bundle content"
```

---

## Execution Order Summary

```
Task 1: Fix backend BASE_URL + resolve_download_url  [backend code fix]
Task 2: Add python_runtime to check-app              [backend code fix]
  → deploy both fixes to server
Task 3: Build ch1_intro chapter bundle               [local script, no code change]
Task 4: Upload chapter bundle + test download loop   [backend test + manual upload]
Task 5: Build sidecar dev bundle + upload            [new script + manual upload]
Task 6: E2E download integration tests               [backend test file]
Task 7: E2E sidecar interaction test                 [sidecar test file]
```

## Known Constraints

- **Sidecar SSE format**: Verify the actual SSE stream event structure by checking `llm-course-sidecar/src/sidecar/services/streaming.py` — `type` field name may differ (`event_type`, `type`, etc.).
- **Session creation API shape**: Check `llm-course-sidecar/docs/api_contract_v1.md` for the exact `POST /api/session/create` request shape and `desktop_context.bundle_paths` keys.
- **LLM key required**: Task 7 requires a real LLM API key (Anthropic or configured provider) for the sidecar to actually call the LLM. Set in `.env` before starting sidecar.
- **`check-app` schema**: If `CheckAppRequest` doesn't already accept arbitrary `installed` keys, update to `dict[str, str]`.
