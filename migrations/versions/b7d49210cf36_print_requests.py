"""Frozen approval requests and durable notification windows.

Revision ID: b7d49210cf36
Revises: a28c4d019e72
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d49210cf36"
down_revision = "a28c4d019e72"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "print_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("destination_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), unique=True),
        sa.Column("request_key", sa.String()),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("job_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("decided_at", sa.Double()),
        sa.Column("decided_by", sa.String()),
        sa.Column("reason", sa.String()),
        sa.UniqueConstraint("owner_id", "request_key"),
    )
    op.create_index("ix_print_requests_owner_id", "print_requests", ["owner_id"])
    op.create_table(
        "request_digest",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_at", sa.Double(), nullable=False),
        sa.Column("due_at", sa.Double(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("request_digest")
    op.drop_table("print_requests")
