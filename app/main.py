from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import admin_bundles, admin_courses, analytics, auth, courses, me, progress, updates, upload
from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.seed import seed_if_needed
from app.db.session import SessionLocal

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not settings.oss_enabled:
    Path("uploads").mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.exception_handler(ApiError)
async def handle_api_error(_, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def on_startup() -> None:
    if settings.app_env == "production" and settings.email_sender_backend != "smtp":
        raise RuntimeError("EMAIL_SENDER_BACKEND must be 'smtp' in production")

    if settings.seed_data:
        try:
            with SessionLocal() as db:
                seed_if_needed(db)
        except SQLAlchemyError as exc:
            raise RuntimeError("Database schema is not ready. Run: alembic upgrade head") from exc


app.include_router(auth.router)
app.include_router(me.router)
app.include_router(courses.router)
app.include_router(updates.router)
app.include_router(progress.router)
app.include_router(analytics.router)
app.include_router(upload.router)
app.include_router(admin_bundles.router)
app.include_router(admin_courses.router)
