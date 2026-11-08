"""Saved price consent and per-submission charge allocations.

Revision ID: d0130eaf254b
Revises: c0130d9e143a
"""

import sqlalchemy as sa
from alembic import op

revision = "d0130eaf254b"
down_revision = "c0130d9e143a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "flush_requests",
        sa.Column("use_authorizations", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "price_quotes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("geometry_key", sa.String(), nullable=False),
        sa.Column("quotes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.Double(), nullable=False),
    )
    op.create_table(
        "unit_charges",
        sa.Column("batch_id", sa.String(), sa.ForeignKey("batches.id"), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("print_jobs.id"), primary_key=True),
        sa.Column("planned_mm", sa.Double(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("reserved_micros", sa.String()),
        sa.Column("cap_micros", sa.String()),
        sa.Column("actual_micros", sa.String()),
        sa.Column("charged_micros", sa.String()),
        sa.Column("authorization", sa.JSON()),
    )


def downgrade():
    op.drop_column("flush_requests", "use_authorizations")
    op.drop_table("unit_charges")
    op.drop_table("price_quotes")
