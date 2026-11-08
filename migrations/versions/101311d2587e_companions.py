"""Companion identity, PIN sessions and durable remote execution."""

import sqlalchemy as sa
from alembic import op

revision = "101311d2587e"
down_revision = "f01310c1476d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("resource_grants") as batch:
        batch.drop_constraint("ck_grant_scope_kind", type_="check")
        batch.create_check_constraint(
            "ck_grant_scope_kind",
            "scope_kind IN ('printer', 'printer_group', 'cartridge', 'location', 'companion')",
        )
    op.create_table(
        "companions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location_id", sa.String(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("bound_user_id", sa.String()),
        sa.Column("key_hash", sa.String(), unique=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("last_seen_at", sa.Double()),
    )
    op.create_table(
        "companion_pins",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("pin_hash", sa.String(), nullable=False),
    )
    op.create_table(
        "companion_sessions",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("companion_id", sa.String(), sa.ForeignKey("companions.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pin_fingerprint", sa.String()),
        sa.Column("expires_at", sa.Double(), nullable=False),
    )
    op.create_index("ix_companion_sessions_companion_id", "companion_sessions", ["companion_id"])
    op.create_table(
        "companion_printers",
        sa.Column("printer_id", sa.String(), sa.ForeignKey("printers.id"), primary_key=True),
        sa.Column("companion_id", sa.String(), sa.ForeignKey("companions.id"), nullable=False),
        sa.Column("local_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.Double()),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("clearance", sa.Integer(), nullable=False),
    )
    op.create_index("ix_companion_printers_companion_id", "companion_printers", ["companion_id"])
    op.create_table(
        "companion_batches",
        sa.Column("batch_id", sa.String(), sa.ForeignKey("batches.id"), primary_key=True),
        sa.Column("companion_id", sa.String(), sa.ForeignKey("companions.id"), nullable=False),
        sa.Column("printer_id", sa.String(), sa.ForeignKey("printers.id"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("go_token", sa.String()),
        sa.Column("result", sa.JSON()),
        sa.Column("stop_mode", sa.String()),
        sa.Column("created_at", sa.Double(), nullable=False),
    )
    op.create_index("ix_companion_batches_companion_id", "companion_batches", ["companion_id"])


def downgrade() -> None:
    op.execute("DELETE FROM resource_grants WHERE scope_kind = 'companion'")
    with op.batch_alter_table("resource_grants") as batch:
        batch.drop_constraint("ck_grant_scope_kind", type_="check")
        batch.create_check_constraint(
            "ck_grant_scope_kind",
            "scope_kind IN ('printer', 'printer_group', 'cartridge', 'location')",
        )
    for name in (
        "companion_batches",
        "companion_printers",
        "companion_sessions",
        "companion_pins",
        "companions",
    ):
        op.drop_table(name)
