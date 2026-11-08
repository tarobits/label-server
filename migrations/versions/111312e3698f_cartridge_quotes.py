"""Requester acceptance when cartridge substitution has no applicable saved quote."""

import sqlalchemy as sa
from alembic import op

revision = "111312e3698f"
down_revision = "101311d2587e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cartridge_quote_offers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("print_jobs.id"), nullable=False),
        sa.Column("printer_id", sa.String(), sa.ForeignKey("printers.id"), nullable=False),
        sa.Column("cartridge_id", sa.String(), nullable=False),
        sa.Column("requester_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("acceptance", sa.JSON()),
        sa.Column("created_at", sa.Double(), nullable=False),
    )
    for column in ("job_id", "requester_id"):
        op.create_index(f"ix_cartridge_quote_offers_{column}", "cartridge_quote_offers", [column])


def downgrade() -> None:
    op.drop_table("cartridge_quote_offers")
