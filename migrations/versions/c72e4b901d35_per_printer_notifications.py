"""Optional per-printer notification event choices."""

import sqlalchemy as sa
from alembic import op

revision = "c72e4b901d35"
down_revision = "b47c9e203a61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_endpoints",
        sa.Column("printer_kinds", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    # Older servers cannot honor exclusions or per-printer choices.
    op.execute("UPDATE notification_endpoints SET enabled = 0 WHERE printer_kinds != '{}'")
    op.drop_column("notification_endpoints", "printer_kinds")
