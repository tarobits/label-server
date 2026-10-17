"""Distinguish administrator alerts and persist empty-cartridge episodes.

Revision ID: f63d84b29a10
Revises: e84a91c607d2
"""

import sqlalchemy as sa
from alembic import op

revision = "f63d84b29a10"
down_revision = "e84a91c607d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notifications", sa.Column("kind", sa.String(), nullable=False, server_default="general")
    )
    op.add_column(
        "notifications", sa.Column("context", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "printer_state", sa.Column("empty_alert_cartridge_id", sa.String(), nullable=True)
    )
    # Before this migration, every administrator-directed notice was an approval digest.
    notices = sa.table("notifications", sa.column("recipient_id"), sa.column("kind"))
    op.execute(
        notices.update()
        .where(notices.c.recipient_id == "administrators")
        .values(kind="approval_digest")
    )


def downgrade():
    op.drop_column("printer_state", "empty_alert_cartridge_id")
    op.drop_column("notifications", "context")
    op.drop_column("notifications", "kind")
