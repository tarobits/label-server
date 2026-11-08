"""Add the 0.13 location, ownership, scoped-grant and audit storage foundation.

Do not assign legacy ownership or activate new authorization policies here. The
administrator workflow must make those choices explicitly before activation.
"""

import sqlalchemy as sa
from alembic import op

revision = "a0130b7c921e"
down_revision = "c94f6b821e35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), sa.ForeignKey("locations.id"), nullable=True),
        sa.CheckConstraint("parent_id != id", name="ck_location_not_own_parent"),
    )
    op.create_index("ix_locations_parent_id", "locations", ["parent_id"])
    for table in ("printers", "cartridges"):
        op.add_column(table, sa.Column("owner_id", sa.String(), nullable=True))
        # SQLite supports adding a nullable FK without recreating referenced tables.
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN location_id VARCHAR REFERENCES locations (id)"
        )
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
        op.create_index(f"ix_{table}_location_id", table, ["location_id"])
    op.add_column("cartridges", sa.Column("notes", sa.String(), nullable=False, server_default=""))
    op.create_table(
        "resource_grants",
        sa.Column("principal_kind", sa.String(), primary_key=True),
        sa.Column("principal_id", sa.String(), primary_key=True),
        sa.Column("scope_kind", sa.String(), primary_key=True),
        sa.Column("scope_id", sa.String(), primary_key=True),
        sa.Column("permission", sa.String(), primary_key=True),
        sa.CheckConstraint("principal_kind IN ('user', 'role')", name="ck_grant_principal_kind"),
        sa.CheckConstraint(
            "scope_kind IN ('printer', 'printer_group', 'cartridge', 'location')",
            name="ck_grant_scope_kind",
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.Double(), nullable=False),
        sa.Column("recorded_at", sa.Double(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')", name="ck_audit_event_outcome"
        ),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("resource_grants")
    op.drop_column("cartridges", "notes")
    for table in ("cartridges", "printers"):
        op.drop_index(f"ix_{table}_location_id", table)
        op.drop_index(f"ix_{table}_owner_id", table)
        # Native DROP COLUMN avoids rebuilding tables referenced by saved batches.
        op.execute(f"ALTER TABLE {table} DROP COLUMN location_id")
        op.drop_column(table, "owner_id")
    op.drop_table("locations")
