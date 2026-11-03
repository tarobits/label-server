"""Audit queued printer substitutions."""

import sqlalchemy as sa
from alembic import op

revision = "e94a6d123f57"
down_revision = "d83f5c012e46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "queue_destination_changes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("job_name", sa.String(), nullable=False),
        sa.Column("copy_ids", sa.JSON(), nullable=False),
        sa.Column("actor", sa.JSON(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("previous_assignment", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
    )
    for field in ("job_id", "source_id", "target_id", "created_at"):
        op.create_index(
            f"ix_queue_destination_changes_{field}", "queue_destination_changes", [field]
        )


def downgrade() -> None:
    op.drop_table("queue_destination_changes")
