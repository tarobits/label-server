"""Stage explicit ownership and recipient assignment before resuming printing."""

import sqlalchemy as sa
from alembic import op

revision = "b0130c8d032f"
down_revision = "a0130b7c921e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "release_migrations",
        sa.Column("version", sa.String(), primary_key=True),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.Double(), nullable=True),
        sa.Column("completed_by", sa.String(), nullable=True),
    )
    connection = op.get_bind()
    existing = any(
        connection.execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first()
        for name in ("printers", "cartridges", "usage_adjustments", "tape_allocations")
    )
    op.bulk_insert(
        table,
        [
            {
                "version": "0.13.0",
                "draft": {},
                "completed_at": None if existing else 0.0,
                "completed_by": None,
            }
        ],
    )
    op.create_table(
        "resource_ownership",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("owner_name", sa.String(), nullable=False),
        sa.Column("effective_at", sa.Double(), nullable=False),
        sa.Column("ended_at", sa.Double(), nullable=True),
    )
    op.create_index("ix_resource_ownership_resource_id", "resource_ownership", ["resource_id"])
    for name in ("tape_allocations", "usage_adjustments"):
        op.add_column(name, sa.Column("recipient_id", sa.String(), nullable=True))
        op.add_column(name, sa.Column("recipient_name", sa.String(), nullable=True))
        op.create_index(f"ix_{name}_recipient_id", name, ["recipient_id"])
    op.add_column("tape_allocations", sa.Column("cartridge_id", sa.String(), nullable=True))
    op.add_column("tape_allocations", sa.Column("charged_micros", sa.String(), nullable=True))


def downgrade() -> None:
    for name in ("tape_allocations", "usage_adjustments"):
        op.drop_index(f"ix_{name}_recipient_id", name)
        op.drop_column(name, "recipient_id")
        op.drop_column(name, "recipient_name")
    op.drop_column("tape_allocations", "cartridge_id")
    op.drop_column("tape_allocations", "charged_micros")
    op.drop_table("resource_ownership")
    op.drop_table("release_migrations")
