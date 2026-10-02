"""Local ownership, template scope, printer destination and notification recipient seams."""

import sqlalchemy as sa
from alembic import op

revision = "c52d171ca013"
down_revision = "b130a210da02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive ALTERs avoid rebuilding tables referenced by queue/history rows.
    for table in ("label_templates", "print_jobs", "print_runs"):
        op.add_column(
            table, sa.Column("owner_id", sa.String(), nullable=False, server_default="local-owner")
        )
    op.add_column(
        "label_templates",
        sa.Column("scope", sa.String(), nullable=False, server_default="personal"),
    )
    for table in ("print_jobs", "print_runs"):
        op.add_column(
            table, sa.Column("destination_id", sa.String(), nullable=False, server_default="main")
        )
    op.add_column(
        "notifications",
        sa.Column("recipient_id", sa.String(), nullable=False, server_default="local-owner"),
    )


def downgrade() -> None:
    op.drop_column("notifications", "recipient_id")
    for table in ("print_jobs", "print_runs"):
        op.drop_column(table, "destination_id")
    op.drop_column("label_templates", "scope")
    for table in ("label_templates", "print_jobs", "print_runs"):
        op.drop_column(table, "owner_id")
