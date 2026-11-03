"""Email notification destinations and verified account recovery."""

import sqlalchemy as sa
from alembic import op

revision = "b47c9e203a61"
down_revision = "a18d6c93b204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(), nullable=True))
    op.create_table(
        "recovery_tokens",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_fingerprint", sa.String(), nullable=False),
        sa.Column("expires_at", sa.Double(), nullable=False),
    )
    op.create_index("ix_recovery_tokens_user_id", "recovery_tokens", ["user_id"])
    op.create_index("ix_recovery_tokens_expires_at", "recovery_tokens", ["expires_at"])
    op.add_column(
        "notification_endpoints",
        sa.Column("transport", sa.String(), nullable=False, server_default="ntfy"),
    )
    op.add_column(
        "notification_endpoints", sa.Column("email", sa.String(), nullable=False, server_default="")
    )
    op.add_column("notification_endpoints", sa.Column("owner_id", sa.String(), nullable=True))
    op.create_index("ix_notification_endpoints_owner_id", "notification_endpoints", ["owner_id"])


def downgrade() -> None:
    # An older server must not treat email destinations as active ntfy endpoints.
    op.execute("UPDATE notification_endpoints SET enabled = 0 WHERE transport = 'email'")
    op.drop_index("ix_notification_endpoints_owner_id", "notification_endpoints")
    op.drop_column("notification_endpoints", "owner_id")
    op.drop_column("notification_endpoints", "email")
    op.drop_column("notification_endpoints", "transport")
    op.drop_table("recovery_tokens")
    op.drop_column("users", "email")
