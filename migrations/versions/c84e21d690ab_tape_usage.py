"""Track cartridge prices and requester tape charges per print attempt."""

import sqlalchemy as sa
from alembic import op

revision = "c84e21d690ab"
down_revision = "b37c60e14f92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cartridges", sa.Column("price_minor", sa.Integer(), nullable=True))
    op.add_column(
        "cartridges", sa.Column("currency", sa.String(3), server_default="EUR", nullable=False)
    )
    op.create_table(
        "tape_allocations",
        sa.Column("batch_id", sa.String(), sa.ForeignKey("batches.id"), primary_key=True),
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("planned_mm", sa.Double(), nullable=False),
        sa.Column("consumed_mm", sa.Double(), nullable=True),
        sa.Column("nominal_length_mm", sa.Double(), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cost_micros", sa.String(), nullable=True),
    )
    op.create_index("ix_tape_allocations_user_id", "tape_allocations", ["user_id"])


def downgrade() -> None:
    op.drop_table("tape_allocations")
    op.drop_column("cartridges", "currency")
    op.drop_column("cartridges", "price_minor")
