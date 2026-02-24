"""Add updated_at, is_deleted to user_submitted_files; add upsert unique index.

Revision ID: 20260224_0007
Revises: 20260224_0006
Create Date: 2026-02-24 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260224_0007"
down_revision = "20260224_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column(
        "user_submitted_files",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "user_submitted_files",
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # Deduplicate: keep only the row with the highest id for each (user_id, chapter_id, filename).
    op.execute("""
        DELETE FROM user_submitted_files
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM user_submitted_files
            GROUP BY user_id, chapter_id, filename
        )
    """)

    # Add unique constraint so each user/chapter/filename has exactly one row.
    op.create_unique_constraint(
        "uq_user_chapter_filename",
        "user_submitted_files",
        ["user_id", "chapter_id", "filename"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_chapter_filename", "user_submitted_files", type_="unique")
    op.drop_column("user_submitted_files", "is_deleted")
    op.drop_column("user_submitted_files", "updated_at")
