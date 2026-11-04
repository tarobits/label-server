"""Per-item completion preferences and durable completion events."""

import sqlalchemy as sa
from alembic import op

revision = "a62d94f07b31"
down_revision = "f04b2a719e63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_jobs",
        sa.Column("notify_on_completion", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.add_column("print_jobs", sa.Column("completion_notified_at", sa.Double()))
    op.add_column("batches", sa.Column("completion_notified_at", sa.Double()))


def downgrade() -> None:
    op.drop_column("batches", "completion_notified_at")
    op.drop_column("print_jobs", "completion_notified_at")
    op.drop_column("print_jobs", "notify_on_completion")
