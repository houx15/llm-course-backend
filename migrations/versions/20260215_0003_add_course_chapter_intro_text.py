"""add intro_text to course_chapters

Revision ID: 20260215_0003
Revises: 20260210_0002
Create Date: 2026-02-15 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260215_0003"
down_revision = "20260210_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("course_chapters", sa.Column("intro_text", sa.Text(), nullable=False, server_default=""))
    op.alter_column("course_chapters", "intro_text", server_default=None)


def downgrade() -> None:
    op.drop_column("course_chapters", "intro_text")
