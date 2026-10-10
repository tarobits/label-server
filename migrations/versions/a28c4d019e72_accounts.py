"""Accounts, role membership, printer grants and opaque login sessions.

Revision ID: a28c4d019e72
Revises: 081e742dc91f
"""

import sqlalchemy as sa
from alembic import op

revision = "a28c4d019e72"
down_revision = "081e742dc91f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("role_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
    )
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
    )
    op.bulk_insert(
        roles,
        [
            {
                "id": "member",
                "name": "Member",
                "permissions": [
                    "templates.write",
                    "assets.write",
                    "print.submit",
                ],
            }
        ],
    )
    op.create_table(
        "user_groups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("user_ids", sa.JSON(), nullable=False),
        sa.Column("role_ids", sa.JSON(), nullable=False),
    )
    op.create_table(
        "printer_grants",
        sa.Column("subject_type", sa.String(), primary_key=True),
        sa.Column("subject_id", sa.String(), primary_key=True),
        sa.Column("printer_id", sa.String(), sa.ForeignKey("printers.id"), primary_key=True),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("csrf_token", sa.String(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("expires_at", sa.Double(), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "registration_codes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role_ids", sa.JSON(), nullable=False),
        sa.Column("group_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("expires_at", sa.Double(), nullable=False),
        sa.Column("redeemed_at", sa.Double()),
        sa.Column("redeemed_by", sa.String(), sa.ForeignKey("users.id")),
        sa.Column("revoked", sa.Boolean(), nullable=False),
    )
    settings = op.create_table(
        "auth_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("registration_code_required", sa.Boolean(), nullable=False),
        sa.Column("approval_notification_debounce_seconds", sa.Integer(), nullable=False),
        sa.Column("approval_notifications_enabled", sa.Boolean(), nullable=False),
    )
    op.bulk_insert(
        settings,
        [
            {
                "id": 1,
                "registration_code_required": True,
                "approval_notification_debounce_seconds": 60,
                "approval_notifications_enabled": True,
            }
        ],
    )
    op.add_column("label_templates", sa.Column("group_id", sa.String()))
    op.execute("UPDATE label_templates SET scope = 'global' WHERE id = 'text'")


def downgrade():
    op.drop_column("label_templates", "group_id")
    op.drop_table("auth_settings")
    op.drop_table("registration_codes")
    op.drop_index("ix_auth_sessions_user_id", "auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("printer_grants")
    op.drop_table("user_groups")
    op.drop_table("roles")
    op.drop_table("users")
