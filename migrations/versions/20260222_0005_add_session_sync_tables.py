"""add session sync tables

Revision ID: 20260222_0005
Revises: 20260222_0004
Create Date: 2026-02-22 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "20260222_0005"
down_revision = "20260222_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_sessions",
        sa.Column("session_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("course_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_sessions_user_id", "learning_sessions", ["user_id"])
    op.create_index("ix_learning_sessions_chapter_id", "learning_sessions", ["chapter_id"])

    op.create_table(
        "session_turn_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.session_id"), nullable=False),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("companion_response", sa.Text(), nullable=False),
        sa.Column("turn_outcome", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "turn_index", name="uq_turn_session_index"),
    )
    op.create_index("ix_session_turn_history_user_id", "session_turn_history", ["user_id"])
    op.create_index("ix_session_turn_history_session_id", "session_turn_history", ["session_id"])

    op.create_table(
        "session_memory_state",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.session_id"), nullable=False, unique=True),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("memory_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_session_memory_state_user_id", "session_memory_state", ["user_id"])

    op.create_table(
        "session_dynamic_report",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.session_id"), nullable=False, unique=True),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("report_md", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_session_dynamic_report_user_id", "session_dynamic_report", ["user_id"])

    op.create_table(
        "user_submitted_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("chapter_id", sa.String(128), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("oss_key", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_submitted_files_user_id", "user_submitted_files", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_submitted_files_user_id", table_name="user_submitted_files")
    op.drop_table("user_submitted_files")
    op.drop_index("ix_session_dynamic_report_user_id", table_name="session_dynamic_report")
    op.drop_table("session_dynamic_report")
    op.drop_index("ix_session_memory_state_user_id", table_name="session_memory_state")
    op.drop_table("session_memory_state")
    op.drop_index("ix_session_turn_history_session_id", table_name="session_turn_history")
    op.drop_index("ix_session_turn_history_user_id", table_name="session_turn_history")
    op.drop_table("session_turn_history")
    op.drop_index("ix_learning_sessions_chapter_id", table_name="learning_sessions")
    op.drop_index("ix_learning_sessions_user_id", table_name="learning_sessions")
    op.drop_table("learning_sessions")
