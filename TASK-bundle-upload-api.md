# Task: bundle-upload-api

## Context
The Knoweia backend (FastAPI + PostgreSQL) manages course content via a `BundleRelease` model. Currently, bundles can only be inserted via database seeds (`SEED_DATA=true`) or direct SQL. There are **no admin API endpoints** to upload/register bundles, which blocks testing and content publishing.

The existing infrastructure includes:
- `BundleRelease` model with fields: `bundle_type`, `scope_id`, `version`, `manifest_json`, `artifact_url`, `sha256`, `size_bytes`, `is_mandatory`
- OSS service for URL resolution and STS credential issuance
- Update check endpoints that serve bundle descriptors to the desktop app
- No admin role/permission system (only basic JWT auth exists)

Tech stack: FastAPI, SQLAlchemy 2.0, PostgreSQL, Alembic, `uv` for dependency management.

## Objective
Add admin API endpoints to manually register, list, and manage bundle releases, plus an optional direct file upload endpoint that stores bundles to Alibaba Cloud OSS. This enables testing the full update flow without direct DB access.

## Dependencies
- Depends on: none
- Branch: feature/bundle-upload-api
- Base: main

## Scope

### Files to Create
- `app/api/routes/admin_bundles.py` — Admin bundle CRUD endpoints
- `app/schemas/admin_bundles.py` — Request/response schemas for admin bundle APIs
- `app/services/bundle_publish_service.py` — Business logic for bundle publishing (validation, OSS upload, DB insert)
- `tests/test_admin_bundles.py` — Integration tests for the new endpoints

### Files to Modify
- `app/api/router.py` — Register the new admin_bundles router under `/v1/admin/bundles`
- `app/services/oss.py` — Add `upload_object()` method for uploading files to OSS (currently only has download/resolve)
- `app/core/config.py` — Add `ADMIN_API_KEY` setting for simple admin auth (no full RBAC needed yet)

### Files NOT to Touch
- `app/api/routes/updates.py` — Existing update check endpoints are fine
- `app/models.py` — BundleRelease model already has all needed fields
- `app/db/seed.py` — Seed data is for dev convenience, not affected
- `migrations/` — No schema changes needed

## Implementation Spec

### Step 1: Add admin auth config
In `app/core/config.py`:
- Add `ADMIN_API_KEY: str = ""` setting
- This is a simple shared secret for admin endpoints (header: `X-Admin-Key`)
- When empty, admin endpoints are disabled (return 403)

### Step 2: Create admin bundle schemas
`app/schemas/admin_bundles.py`:

```python
class BundlePublishRequest(BaseModel):
    bundle_type: str          # "chapter", "app_agents", "experts", "experts_shared", "python_runtime"
    scope_id: str             # e.g., "course1/ch1_intro", "core", "data_inspector"
    version: str              # semantic version, e.g., "1.0.0"
    artifact_url: str         # OSS URL, https URL, or "upload" for direct upload
    sha256: str               # SHA256 checksum
    size_bytes: int           # File size in bytes
    is_mandatory: bool = True
    manifest_json: dict = {}  # Optional metadata (e.g., required_experts)

class BundlePublishResponse(BaseModel):
    id: str
    bundle_type: str
    scope_id: str
    version: str
    artifact_url: str
    created_at: str

class BundleListResponse(BaseModel):
    bundles: list[BundlePublishResponse]
    total: int

class BundleUploadResponse(BaseModel):
    artifact_url: str         # The OSS URL where the file was stored
    sha256: str               # Computed SHA256
    size_bytes: int           # Actual file size
```

### Step 3: Add OSS upload capability
In `app/services/oss.py`, add:

```python
async def upload_bundle(
    file_content: bytes,
    bundle_type: str,
    scope_id: str,
    version: str,
) -> str:
    """Upload bundle tar.gz to OSS. Returns the object key."""
    # Object key: bundles/{bundle_type}/{scope_id}/{version}/bundle.tar.gz
    # Use oss2 SDK to put_object
    # Return the object key (not full URL — artifact_url resolution handles that)
```

### Step 4: Create admin bundle routes
`app/api/routes/admin_bundles.py`:

**`POST /v1/admin/bundles/publish`** — Register a bundle release
- Auth: `X-Admin-Key` header
- Body: `BundlePublishRequest`
- Validates: unique (bundle_type, scope_id, version)
- Inserts into `bundle_releases` table
- Returns: `BundlePublishResponse`

**`POST /v1/admin/bundles/upload`** — Upload file + register in one step
- Auth: `X-Admin-Key` header
- Multipart form: `file` (tar.gz), `bundle_type`, `scope_id`, `version`, `is_mandatory`
- Computes SHA256 and size from uploaded file
- Uploads to OSS via `upload_bundle()`
- Inserts BundleRelease with the OSS object key as `artifact_url`
- Returns: `BundlePublishResponse`

**`GET /v1/admin/bundles`** — List all bundle releases
- Auth: `X-Admin-Key` header
- Query params: `bundle_type` (optional filter), `scope_id` (optional filter), `limit`, `offset`
- Returns: `BundleListResponse`

**`GET /v1/admin/bundles/{bundle_id}`** — Get single bundle details
- Auth: `X-Admin-Key` header
- Returns: Full bundle details including manifest_json

**`DELETE /v1/admin/bundles/{bundle_id}`** — Delete a bundle release
- Auth: `X-Admin-Key` header
- Soft delete or hard delete the DB record
- Does NOT delete the OSS object (manual cleanup)
- Returns: 204 No Content

### Step 5: Create bundle publish service
`app/services/bundle_publish_service.py`:
- `publish_bundle(db, request)` — Validate uniqueness, insert, return
- `upload_and_publish(db, file, metadata)` — Compute hash, upload to OSS, insert, return
- `list_bundles(db, filters)` — Query with optional filters
- `delete_bundle(db, bundle_id)` — Delete record

### Step 6: Register router
In `app/api/router.py`:
- Add `from .routes.admin_bundles import router as admin_bundles_router`
- Include: `api_router.include_router(admin_bundles_router, prefix="/admin/bundles", tags=["admin"])`

### Step 7: Write integration tests
`tests/test_admin_bundles.py`:
- Test publish with valid data → 201
- Test publish with duplicate (type, scope, version) → 409
- Test list with filters
- Test delete
- Test auth: missing/wrong API key → 403
- Test upload with file (mock OSS or use local fallback)

## Testing Requirements
- All endpoints return correct status codes
- Duplicate bundle version is rejected (409 Conflict)
- Admin key auth works (valid key → success, missing/invalid → 403)
- List endpoint supports filtering by bundle_type and scope_id
- Upload endpoint computes correct SHA256
- Published bundles appear in existing `/v1/updates/check-app` and `/v1/updates/check-chapter` responses

## Acceptance Criteria
- [ ] `POST /v1/admin/bundles/publish` registers a bundle release
- [ ] `POST /v1/admin/bundles/upload` uploads file to OSS and registers
- [ ] `GET /v1/admin/bundles` lists bundles with filtering
- [ ] `DELETE /v1/admin/bundles/{id}` removes a bundle
- [ ] Admin auth via `X-Admin-Key` header works
- [ ] Existing update check endpoints serve newly published bundles
- [ ] Integration tests pass

## Notes
- For local development without OSS, the upload endpoint should support a fallback: store files in a local `./uploads/` directory and serve them via a static file route. Check `OSS_ENABLED` config flag.
- The `manifest_json` field is flexible JSONB. For chapter bundles, include `required_experts: ["data_inspector"]`. For python_runtime, include `platform: "darwin-arm64"`.
- Version comparison in `check_bundle_required` uses simple string comparison. Consider using `packaging.version.Version` for proper semver, but this is out of scope — just ensure versions follow semver format.
- The `artifact_url` field supports multiple formats: `oss://bucket/key`, `https://...`, or plain object keys. The existing `resolve_artifact_url` handles all these.
