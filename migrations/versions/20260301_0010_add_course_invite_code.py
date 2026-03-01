"""Add invite_code column to courses table.

Revision ID: 20260301_0010
Revises: 20260226_0009
Create Date: 2026-03-01 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260301_0010"
down_revision = "20260226_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("invite_code", sa.String(8), nullable=True),
    )
    op.create_unique_constraint("uq_courses_invite_code", "courses", ["invite_code"])
    op.create_index("ix_courses_invite_code", "courses", ["invite_code"])


def downgrade() -> None:
    op.drop_index("ix_courses_invite_code", table_name="courses")
    op.drop_constraint("uq_courses_invite_code", "courses", type_="unique")
    op.drop_column("courses", "invite_code")
