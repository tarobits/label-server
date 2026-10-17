"""Persistent ntfy endpoints and independent delivery attempts.

Revision ID: a73b159dc820
Revises: f63d84b29a10
"""

import time
import uuid

import sqlalchemy as sa
from alembic import op
from pydantic_settings import BaseSettings, SettingsConfigDict

revision = "a73b159dc820"
down_revision = "f63d84b29a10"
branch_labels = None
depends_on = None


class LegacySettings(BaseSettings):
    # Import the existing installation's single topic once, never during startup.
    model_config = SettingsConfigDict(env_prefix="LABEL_", env_file=".env", extra="ignore")
    ntfy_url: str = ""
    ntfy_topic: str = ""
    ntfy_token: str = ""


def upgrade():
    op.add_column("notifications", sa.Column("routed_at", sa.Double(), nullable=True))
    op.create_table(
        "notification_endpoints",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("destination_ids", sa.JSON(), nullable=False),
        sa.Column("minimum_level", sa.String(), nullable=False),
        sa.Column("role_ids", sa.JSON(), nullable=False),
        sa.Column("kinds", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("deleted_at", sa.Double(), nullable=True),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "notification_id", sa.String(), sa.ForeignKey("notifications.id"), nullable=False
        ),
        sa.Column(
            "endpoint_id", sa.String(), sa.ForeignKey("notification_endpoints.id"), nullable=False
        ),
        sa.Column("endpoint_revision", sa.Integer(), nullable=False),
        sa.Column("endpoint_name", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.Double(), nullable=False),
        sa.Column("delivered_at", sa.Double(), nullable=True),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.UniqueConstraint("notification_id", "endpoint_id"),
    )
    op.create_index(
        "ix_notification_deliveries_notification_id", "notification_deliveries", ["notification_id"]
    )
    connection = op.get_bind()
    # A fresh installation has no legacy channel to import. In particular, test
    # installations must not inherit a developer's configured live endpoint.
    if not connection.execute(sa.text("SELECT id FROM users LIMIT 1")).first():
        return
    settings = LegacySettings()
    if not settings.ntfy_url or not settings.ntfy_topic:
        return
    endpoints = sa.Table("notification_endpoints", sa.MetaData(), autoload_with=connection)
    connection.execute(
        endpoints.insert().values(
            id=str(uuid.uuid4()),
            name="Imported administrator notifications",
            url=settings.ntfy_url.rstrip("/"),
            topic=settings.ntfy_topic,
            token=settings.ntfy_token,
            enabled=True,
            destination_ids=[],
            minimum_level="full",
            role_ids=["administrator"],
            kinds=[
                "general",
                "empty_tape",
                "printer_blocked",
                "batch_review",
                "tape_waiting",
                "approval_digest",
            ],
            revision=1,
            created_at=time.time(),
        )
    )


def downgrade():
    op.drop_index(
        "ix_notification_deliveries_notification_id", table_name="notification_deliveries"
    )
    op.drop_table("notification_deliveries")
    op.drop_table("notification_endpoints")
    op.drop_column("notifications", "routed_at")
