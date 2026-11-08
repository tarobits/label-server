"""Explicit requester and cartridge-funded retry authorization."""

import sqlalchemy as sa
from alembic import op

revision = "f01310c1476d"
down_revision = "e0130fb0365c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retry_offers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), sa.ForeignKey("batches.id"), nullable=False),
        sa.Column("source_job_id", sa.String(), sa.ForeignKey("print_jobs.id"), nullable=False),
        sa.Column("copy_ids", sa.JSON(), nullable=False),
        sa.Column("requester_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_name", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("cartridge_id", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("print_jobs.id")),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("accepted_at", sa.Double()),
    )
    for column in ("request_key", "batch_id", "requester_id"):
        op.create_index(f"ix_retry_offers_{column}", "retry_offers", [column])


def downgrade() -> None:
    op.drop_table("retry_offers")
