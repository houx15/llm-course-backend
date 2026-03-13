"""Add parts column to courses table.

Revision ID: 20260313_0013
Revises: 20260301_0012
Create Date: 2026-03-13 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260313_0013"
down_revision = "20260301_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("parts", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("courses", "parts")
