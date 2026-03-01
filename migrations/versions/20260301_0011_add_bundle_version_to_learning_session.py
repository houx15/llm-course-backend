"""Add bundle_version to learning_sessions.

Revision ID: 20260301_0011
Revises: 20260301_0010
Create Date: 2026-03-01 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260301_0011"
down_revision = "20260301_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learning_sessions",
        sa.Column("bundle_version", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("learning_sessions", "bundle_version")
