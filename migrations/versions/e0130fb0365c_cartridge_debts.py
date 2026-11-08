"""Unassigned cartridge debts and explicit repayment allocations."""

import sqlalchemy as sa
from alembic import op

revision = "e0130fb0365c"
down_revision = "d0130eaf254b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tape_allocations", sa.Column("recipient_assigned_at", sa.Double()))
    op.add_column(
        "usage_adjustments",
        sa.Column("cartridge_allocations", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column("usage_adjustments", sa.Column("requested_allocations", sa.JSON()))


def downgrade() -> None:
    op.drop_column("usage_adjustments", "requested_allocations")
    op.drop_column("usage_adjustments", "cartridge_allocations")
    op.drop_column("tape_allocations", "recipient_assigned_at")
