"""Replace notification permission filters with explicit printer selection.

Revision ID: c91d8e5a206b
Revises: a73b159dc820
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "c91d8e5a206b"
down_revision = "a73b159dc820"
branch_labels = None
depends_on = None
DEFAULT_PRIORITIES = {
    "general": 3,
    "empty_tape": 4,
    "printer_blocked": 4,
    "batch_review": 4,
    "tape_waiting": 3,
    "approval_digest": 3,
}


def upgrade():
    # ALTER preserves the referenced endpoint table and delivery history.
    op.add_column(
        "notification_endpoints",
        sa.Column("all_printers", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "notification_endpoints",
        sa.Column(
            "priorities", sa.JSON(), nullable=False, server_default=json.dumps(DEFAULT_PRIORITIES)
        ),
    )
    op.drop_column("notification_endpoints", "minimum_level")
    op.drop_column("notification_endpoints", "role_ids")
    connection = op.get_bind()
    endpoints = sa.Table("notification_endpoints", sa.MetaData(), autoload_with=connection)
    for endpoint in connection.execute(sa.select(endpoints)).mappings():
        # Empty filters previously meant unrestricted. Make that choice explicit.
        connection.execute(
            endpoints.update()
            .where(endpoints.c.id == endpoint["id"])
            .values(all_printers=not endpoint["destination_ids"], revision=endpoint["revision"] + 1)
        )
    connection.execute(
        sa.text(
            "UPDATE notification_deliveries SET cancelled = 1 WHERE delivered_at IS NULL AND cancelled = 0"
        )
    )
    # Settle routed parents too: otherwise they suppress later tape reminders.
    connection.execute(
        sa.text("""
        UPDATE notifications
        SET delivered_at = (
            SELECT MAX(delivered_at) FROM notification_deliveries
            WHERE notification_id = notifications.id
        ),
        cancelled = CASE WHEN EXISTS (
            SELECT 1 FROM notification_deliveries
            WHERE notification_id = notifications.id AND delivered_at IS NOT NULL
        ) THEN 0 ELSE 1 END,
        last_error = NULL
        WHERE routed_at IS NOT NULL AND delivered_at IS NULL AND cancelled = 0
            AND EXISTS (SELECT 1 FROM notification_deliveries WHERE notification_id = notifications.id)
    """)
    )


def downgrade():
    connection = op.get_bind()
    endpoints = sa.Table("notification_endpoints", sa.MetaData(), autoload_with=connection)
    # The former representation used an empty list for unrestricted scopes.
    connection.execute(
        endpoints.update().where(endpoints.c.all_printers.is_(True)).values(destination_ids=[])
    )
    op.add_column(
        "notification_endpoints",
        sa.Column("minimum_level", sa.String(), nullable=False, server_default="request"),
    )
    op.add_column(
        "notification_endpoints",
        sa.Column(
            "role_ids", sa.JSON(), nullable=False, server_default=json.dumps(["administrator"])
        ),
    )
    op.drop_column("notification_endpoints", "all_printers")
    op.drop_column("notification_endpoints", "priorities")
