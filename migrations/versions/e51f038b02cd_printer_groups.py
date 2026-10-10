"""Independent printers and group routing.

Revision ID: e51f038b02cd
Revises: d804a91c3044
"""

import sqlalchemy as sa
from alembic import op

revision = "e51f038b02cd"
down_revision = "d804a91c3044"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "printers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("driver", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
    )
    op.create_table(
        "printer_groups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("printer_ids", sa.JSON(), nullable=False),
        sa.Column("automatic_printing_held", sa.Boolean(), nullable=False, server_default="0"),
    )
    with op.batch_alter_table("printer_state") as batch:
        batch.add_column(
            sa.Column("printer_id", sa.String(), nullable=False, server_default="main")
        )
        batch.create_unique_constraint("uq_printer_state_printer_id", ["printer_id"])
    with op.batch_alter_table("batches") as batch:
        batch.add_column(
            sa.Column("printer_id", sa.String(), nullable=False, server_default="main")
        )
    with op.batch_alter_table("flush_requests") as batch:
        batch.add_column(
            sa.Column("printer_id", sa.String(), nullable=False, server_default="main")
        )
        batch.add_column(
            sa.Column("destination_id", sa.String(), nullable=False, server_default="main")
        )
    with op.batch_alter_table("print_runs") as batch:
        batch.add_column(sa.Column("assigned_printer_id", sa.String(), nullable=True))


def downgrade():
    # Native column removal preserves referenced tables and their existing rows.
    # Recreating batches/print_runs would fail with populated foreign keys.
    op.drop_column("print_runs", "assigned_printer_id")
    op.drop_column("flush_requests", "destination_id")
    op.drop_column("flush_requests", "printer_id")
    op.drop_column("batches", "printer_id")
    with op.batch_alter_table("printer_state") as batch:
        batch.drop_constraint("uq_printer_state_printer_id", type_="unique")
        batch.drop_column("printer_id")
    op.drop_table("printer_groups")
    op.drop_table("printers")
