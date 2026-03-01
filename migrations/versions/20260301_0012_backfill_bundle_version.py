"""Backfill existing learning_sessions with bundle_version='1.0.0'.

Revision ID: 20260301_0012
Revises: 20260301_0011
Create Date: 2026-03-01 16:00:00.000000
"""

from alembic import op


revision = "20260301_0012"
down_revision = "20260301_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE learning_sessions SET bundle_version = '1.0.0' WHERE bundle_version IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE learning_sessions SET bundle_version = NULL WHERE bundle_version = '1.0.0'"
    )
