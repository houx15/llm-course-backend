"""add overview fields to courses

Revision ID: 20260222_0004
Revises: 20260215_0003
Create Date: 2026-02-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260222_0004"
down_revision = "20260215_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("overview_experience", "overview_gains", "overview_necessity", "overview_journey"):
        op.add_column("courses", sa.Column(col, sa.Text(), nullable=False, server_default=""))
        op.alter_column("courses", col, server_default=None)


def downgrade() -> None:
    for col in ("overview_experience", "overview_gains", "overview_necessity", "overview_journey"):
        op.drop_column("courses", col)
