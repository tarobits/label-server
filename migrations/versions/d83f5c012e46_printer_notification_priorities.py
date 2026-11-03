"""Per-printer ntfy event priorities."""

import sqlalchemy as sa
from alembic import op

revision = "d83f5c012e46"
down_revision = "c72e4b901d35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_endpoints",
        sa.Column("printer_priorities", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.execute("UPDATE notification_endpoints SET enabled = 0 WHERE printer_priorities != '{}'")
    op.drop_column("notification_endpoints", "printer_priorities")
