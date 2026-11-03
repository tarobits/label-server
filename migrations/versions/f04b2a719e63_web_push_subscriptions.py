"""Per-installation Web Push subscriptions."""

import sqlalchemy as sa
from alembic import op

revision = "f04b2a719e63"
down_revision = "e94a6d123f57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_endpoints",
        sa.Column("push_subscription", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column("notification_endpoints", sa.Column("push_session_hash", sa.String()))


def downgrade() -> None:
    op.execute("UPDATE notification_endpoints SET enabled = 0 WHERE transport = 'push'")
    op.drop_column("notification_endpoints", "push_session_hash")
    op.drop_column("notification_endpoints", "push_subscription")
