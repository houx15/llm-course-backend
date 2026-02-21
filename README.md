# llm-course-backend

FastAPI + PostgreSQL backend for the desktop Socratic multi-agent learning platform.

## Scope

This backend is responsible for:
- Email/password auth and device session tokens
- Course enrollment and chapter listing
- Bundle update checks (`check-app`, `check-chapter`)
- Progress sync and analytics ingestion

The backend does **not** execute CA/RMA/MA loops and does **not** store raw LLM keys.

## Stack

- FastAPI
- SQLAlchemy 2
- PostgreSQL 16
- Docker Compose

## Default Ports

- API: `10723`
- PostgreSQL (host mapped): `15432`

## Project Layout

```text
llm-course-backend/
├── app/
│   ├── api/routes/        # HTTP route groups
│   ├── core/              # config, errors, security helpers
│   ├── db/                # engine/session/bootstrap/seed
│   ├── schemas/           # pydantic request/response models
│   ├── services/          # domain service helpers
│   ├── main.py            # FastAPI app entry
│   └── models.py          # SQLAlchemy models
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## Quick Start (Docker, Recommended)

```bash
cd llm-course-backend
docker compose up --build
```

After startup:
- Health: `http://localhost:10723/healthz`
- OpenAPI: `http://localhost:10723/docs`
- DB migrations are applied automatically before API startup (`alembic upgrade head`).

## Local Run (without Docker)

1. Create local env file:
```bash
cp .env.example .env
```

2. Install dependencies with `uv`:
```bash
uv sync --dev
```

3. Ensure Postgres is running and `DATABASE_URL` points to it.

4. Apply migrations:
```bash
uv run alembic upgrade head
```

5. Start API:
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 10723 --reload
```

## Environment Variables

Main variables (see `.env.example`):
- `APP_PORT=10723`
- `DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:15432/llm_course`
- `JWT_SECRET=change-me`
- `ACCESS_TOKEN_EXPIRE_SECONDS=3600`
- `REFRESH_TOKEN_EXPIRE_SECONDS=2592000`
- `EMAIL_CODE_EXPIRE_SECONDS=300`
- `DEV_FIXED_EMAIL_CODE=` (optional, non-production only)
- `EMAIL_SENDER_BACKEND=console|smtp`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_FROM_EMAIL`
- `AUTH_CODE_WINDOW_SECONDS=600`
- `AUTH_CODE_MAX_PER_EMAIL_WINDOW=5`
- `AUTH_CODE_MAX_PER_IP_WINDOW=20`
- `AUTH_CODE_COOLDOWN_SECONDS=30`
- `SEED_DATA=true`
- `ADMIN_API_KEY=` (required for `/v1/admin/*`, including bundles and courses)
- `OSS_ENABLED=false`
- `OSS_REGION_ID=oss-cn-...`
- `OSS_ENDPOINT=oss-cn-....aliyuncs.com`
- `OSS_BUCKET_NAME=...`
- `OSS_CDN_DOMAIN=...` (optional)
- `OSS_ACCESS_KEY_ID=...` (for signed URLs / STS)
- `OSS_ACCESS_KEY_SECRET=...` (for signed URLs / STS)
- `OSS_ROLE_ARN=...` (for STS)
- `OSS_STS_DURATION_SECONDS=1800`
- `OSS_DOWNLOAD_SIGNED_URL_ENABLED=false`
- `OSS_DOWNLOAD_URL_EXPIRE_SECONDS=900`
- `OSS_BUNDLE_PREFIX=bundles/`

Production requirement:
- `APP_ENV=production` must use `EMAIL_SENDER_BACKEND=smtp`
- `DEV_FIXED_EMAIL_CODE` should be empty in production.

Dev convenience:
- If `DEV_FIXED_EMAIL_CODE` is set and `APP_ENV!=production`, register accepts this code directly.
- This is temporary for local/dev testing before SMTP/domain is ready.

Auth flow:
- Register: request email code (`purpose=register`) -> register with `email + verification_code + password`.
- Login: `email + password` (no email code).

## Seed Data

When `SEED_DATA=true`, startup inserts:
- Course `SOC101`
- Chapters `ch1_intro`, `ch2_pandas`
- Sample bundle releases for:
  - `app_agents/core`
  - `experts_shared/shared`
  - `chapter/{course_id}/ch1_intro`
  - `experts/data_inspector`
  - `experts/concept_explainer`

## API Groups Implemented

- `POST /v1/auth/request-email-code`
- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`
- `GET /v1/me`
- `GET /v1/courses/my`
- `POST /v1/courses/join`
- `GET /v1/courses/{course_id}`
- `GET /v1/courses/{course_id}/chapters`
- `POST /v1/updates/check-app`
- `POST /v1/updates/check-chapter`
- `GET /v1/updates/runtime-config` — returns Miniconda installer URL + pip/conda mirror config per platform
- `POST /v1/oss/download-credentials`
- `POST /v1/oss/resolve-artifact-url`
- `POST /v1/admin/courses`
- `GET /v1/admin/courses/{course_id}`
- `PUT /v1/admin/courses/{course_id}/chapters/{chapter_code}`
- `PATCH /v1/admin/courses/{course_id}/chapters/{chapter_code}/intro`
- `POST /v1/admin/bundles/publish`
- `POST /v1/admin/bundles/upload`
- `GET /v1/admin/bundles`
- `GET /v1/admin/bundles/{bundle_id}`
- `DELETE /v1/admin/bundles/{bundle_id}`
- `POST /v1/progress/chapter`
- `POST /v1/analytics/events:ingest`

Chapter visibility rule:
- `GET /v1/courses/{course_id}/chapters` only returns chapters that already have a `chapter` bundle release (`scope_id={course_id}/{chapter_code}`).

## Backend TODO Roadmap

### P0 (current focus, do now)

- [x] Add Alembic migrations and stop relying on startup `create_all`.
- [x] Integrate real OTP email provider and disable `dev_code` in production.
- [x] Add rate limiting and anti-abuse controls for auth code endpoints.
- [x] Tighten authorization checks for course/chapter scoped endpoints.
- [x] Add integration tests for end-to-end core flow:
  - auth -> join course -> list chapters -> check updates -> progress -> analytics
- [x] Define and enforce a stable error code catalog.

### P1 (deferred for future)

- [ ] Structured logging and request IDs.
- [ ] Metrics/observability and readiness diagnostics.
- [ ] Improved idempotency strategy for ingest endpoints.
- [ ] CORS allowlist and stronger secret management policies.
- [ ] Backup/restore and data retention policy.

### P2 (deferred for future)

- [ ] Admin/content APIs for bundle publishing lifecycle.
- [ ] Enforce bundle compatibility policy (`min_desktop_version`, `min_sidecar_version`).
- [ ] Optional async pipelines (Redis/jobs) for heavy background tasks.

## Error Code Catalog (P0)

Auth/security:
- `UNAUTHORIZED`
- `INVALID_TOKEN`
- `INVALID_USER`
- `EMAIL_ALREADY_REGISTERED`
- `USER_NOT_FOUND`
- `VERIFICATION_CODE_NOT_FOUND`
- `VERIFICATION_CODE_EXPIRED`
- `INVALID_VERIFICATION_CODE`
- `INVALID_CREDENTIALS`
- `UNSUPPORTED_AUTH_FLOW`
- `INVALID_REFRESH_TOKEN`
- `DEVICE_MISMATCH`
- `REFRESH_TOKEN_EXPIRED`
- `EMAIL_SEND_FAILED`
- `SERVER_MISCONFIGURED`
- `TOO_MANY_REQUESTS`

Course/content:
- `COURSE_NOT_FOUND`
- `COURSE_ACCESS_DENIED`
- `CHAPTER_NOT_FOUND`

## Integration Tests (P0)

Install test dependencies:
```bash
uv sync --dev
```

Run tests against a running backend:
```bash
RUN_INTEGRATION=1 BASE_URL=http://localhost:10723 uv run pytest -q tests
```

## Create Test User (Dev)

After `alembic upgrade head`, you can create/update a login user directly:

```bash
uv run python app/scripts/create_test_user.py \
  --email student@example.com \
  --password StrongPass123 \
  --name "Test Student" \
  --course-code SOC101
```

This script will:
- create the user if missing, or update display name/password if existing
- optionally enroll the user into the given active course

## Deployment Guide: Bundle Upload API

When deploying new features (e.g., bundle-upload-api) to your server, follow these steps:

### Step 1: Pull Latest Code on Server

```bash
cd /path/to/llm-course-backend
git pull origin main
```

Or if you're on a feature branch:
```bash
git fetch origin
git checkout feature/bundle-upload-api
git pull origin feature/bundle-upload-api
```

### Step 2: Update Environment Variables

Edit `.env` on the server to add the new config options:

```bash
nano .env
```

Add/verify these variables:

```env
# Admin API key - REQUIRED for /v1/admin/* endpoints
ADMIN_API_KEY=your-secure-admin-key-here

# OSS config for bundle uploads
OSS_ENABLED=true
OSS_REGION_ID=oss-cn-hangzhou
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET_NAME=your-bucket-name
OSS_ACCESS_KEY_ID=your-access-key-id
OSS_ACCESS_KEY_SECRET=your-access-key-secret
OSS_BUNDLE_PREFIX=bundles/
```

For local dev without OSS, set `OSS_ENABLED=false` — uploads will be stored in `./uploads/`.

### Step 3: Rebuild and Restart Docker Containers

```bash
docker compose down
docker compose up --build -d
```

This will:
- Rebuild the Docker image with new code
- Apply any pending migrations automatically
- Start the API on port 10723

### Step 4: Verify Deployment

1. Check container logs:
```bash
docker compose logs -f api
```

2. Test health endpoint:
```bash
curl http://localhost:10723/healthz
```

3. Test admin bundles endpoint:
```bash
curl -H "X-Admin-Key: your-secure-admin-key-here" \
     http://localhost:10723/v1/admin/bundles
```

4. Check OpenAPI docs:
```bash
open http://localhost:10723/docs
```

### Step 5: Publish a Test Bundle (Optional)

```bash
curl -X POST http://localhost:10723/v1/admin/bundles/publish \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-secure-admin-key-here" \
  -d '{
    "bundle_type": "experts",
    "scope_id": "data_inspector",
    "version": "1.0.0",
    "artifact_url": "https://example.com/bundle.tar.gz",
    "sha256": "abc123...",
    "size_bytes": 12345,
    "is_mandatory": true
  }'
```

### Troubleshooting

- **403 Forbidden on admin endpoints**: Verify `ADMIN_API_KEY` is set and matches the header
- **OSS upload fails**: Check OSS credentials and bucket permissions
- **Container won't start**: Run `docker compose logs api` for error details

## Dev Notes

- Email sending is currently stubbed in non-production; auth code is returned as `dev_code`.
- DB schema is migration-driven via Alembic.
- P1 and P2 are intentionally deferred while focusing on P0.
