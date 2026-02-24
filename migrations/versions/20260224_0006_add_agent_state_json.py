"""add agent_state_json to session_memory_state

Revision ID: 20260224_0006
Revises: 20260222_0005
Create Date: 2026-02-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260224_0006"
down_revision = "20260222_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_memory_state",
        sa.Column("agent_state_json", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("session_memory_state", "agent_state_json")
