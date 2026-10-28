"""Append-only usage account payments and corrections."""

import sqlalchemy as sa
from alembic import op

revision = "d91e6a27b430"
down_revision = "c84e21d690ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_adjustments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_name", sa.String(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("note", sa.String(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
    )
    op.create_index("ix_usage_adjustments_user_id", "usage_adjustments", ["user_id"])


def downgrade() -> None:
    op.drop_table("usage_adjustments")
