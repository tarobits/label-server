"""Recipient-specific read state, independent of external notification delivery."""

import sqlalchemy as sa
from alembic import op

revision = "c0130d9e143a"
down_revision = "b0130c8d032f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_reads",
        sa.Column(
            "notification_id",
            sa.String(),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("read_at", sa.Double(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notification_reads")
