"""initial schema

Revision ID: 20260207_0001
Revises: 
Create Date: 2026-02-07 23:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260207_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "email_verification_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_verification_codes_email", "email_verification_codes", ["email"], unique=False)

    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructor", sa.String(length=120), nullable=False),
        sa.Column("semester", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_code", name="uq_courses_code"),
    )
    op.create_index("ix_courses_course_code", "courses", ["course_code"], unique=False)

    op.create_table(
        "device_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_device_sessions_refresh_hash"),
    )
    op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"], unique=False)
    op.create_index("ix_device_sessions_device_id", "device_sessions", ["device_id"], unique=False)

    op.create_table(
        "course_chapters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_code", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "chapter_code", name="uq_course_chapter_code"),
    )
    op.create_index("ix_course_chapters_course_id", "course_chapters", ["course_id"], unique=False)

    op.create_table(
        "enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "course_id", name="uq_enrollment_user_course"),
    )
    op.create_index("ix_enrollments_user_id", "enrollments", ["user_id"], unique=False)
    op.create_index("ix_enrollments_course_id", "enrollments", ["course_id"], unique=False)

    op.create_table(
        "chapter_progress",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_session_id", sa.String(length=255), nullable=True),
        sa.Column("task_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["course_chapters.id"]),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "chapter_id", name="uq_progress_user_chapter"),
    )
    op.create_index("ix_chapter_progress_user_id", "chapter_progress", ["user_id"], unique=False)
    op.create_index("ix_chapter_progress_course_id", "chapter_progress", ["course_id"], unique=False)
    op.create_index("ix_chapter_progress_chapter_id", "chapter_progress", ["chapter_id"], unique=False)

    op.create_table(
        "bundle_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bundle_type", sa.String(length=64), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bundle_type", "scope_id", "version", name="uq_bundle_release"),
    )
    op.create_index("ix_bundle_releases_bundle_type", "bundle_releases", ["bundle_type"], unique=False)
    op.create_index("ix_bundle_releases_scope_id", "bundle_releases", ["scope_id"], unique=False)

    op.create_table(
        "analytics_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("course_id", sa.String(length=128), nullable=True),
        sa.Column("chapter_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_analytics_events_event_id"),
    )
    op.create_index("ix_analytics_events_user_id", "analytics_events", ["user_id"], unique=False)
    op.create_index("ix_analytics_events_course_id", "analytics_events", ["course_id"], unique=False)
    op.create_index("ix_analytics_events_chapter_id", "analytics_events", ["chapter_id"], unique=False)
    op.create_index("ix_analytics_events_session_id", "analytics_events", ["session_id"], unique=False)
    op.create_index("ix_analytics_events_event_id", "analytics_events", ["event_id"], unique=False)

    op.create_table(
        "auth_rate_limit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_rate_limit_events_action", "auth_rate_limit_events", ["action"], unique=False)
    op.create_index("ix_auth_rate_limit_events_identifier", "auth_rate_limit_events", ["identifier"], unique=False)
    op.create_index("ix_auth_rate_limit_events_created_at", "auth_rate_limit_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limit_events_created_at", table_name="auth_rate_limit_events")
    op.drop_index("ix_auth_rate_limit_events_identifier", table_name="auth_rate_limit_events")
    op.drop_index("ix_auth_rate_limit_events_action", table_name="auth_rate_limit_events")
    op.drop_table("auth_rate_limit_events")

    op.drop_index("ix_analytics_events_event_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_session_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_chapter_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_course_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_user_id", table_name="analytics_events")
    op.drop_table("analytics_events")

    op.drop_index("ix_bundle_releases_scope_id", table_name="bundle_releases")
    op.drop_index("ix_bundle_releases_bundle_type", table_name="bundle_releases")
    op.drop_table("bundle_releases")

    op.drop_index("ix_chapter_progress_chapter_id", table_name="chapter_progress")
    op.drop_index("ix_chapter_progress_course_id", table_name="chapter_progress")
    op.drop_index("ix_chapter_progress_user_id", table_name="chapter_progress")
    op.drop_table("chapter_progress")

    op.drop_index("ix_enrollments_course_id", table_name="enrollments")
    op.drop_index("ix_enrollments_user_id", table_name="enrollments")
    op.drop_table("enrollments")

    op.drop_index("ix_course_chapters_course_id", table_name="course_chapters")
    op.drop_table("course_chapters")

    op.drop_index("ix_device_sessions_device_id", table_name="device_sessions")
    op.drop_index("ix_device_sessions_user_id", table_name="device_sessions")
    op.drop_table("device_sessions")

    op.drop_index("ix_courses_course_code", table_name="courses")
    op.drop_table("courses")

    op.drop_index("ix_email_verification_codes_email", table_name="email_verification_codes")
    op.drop_table("email_verification_codes")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
