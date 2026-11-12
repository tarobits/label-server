"""Separate payer-reported payments from confirmed ledger adjustments.

Revision ID: 45e091c8b732
Revises: 34df80b7a621
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "45e091c8b732"
down_revision = "34df80b7a621"
branch_labels = None
depends_on = None


def upgrade():
    # Identity snapshots deliberately survive account purging, like usage_adjustments.
    op.create_table(
        "payment_reports",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column(
            "username", sa.String().with_variant(LONGTEXT(), "mysql", "mariadb"), nullable=False
        ),
        sa.Column("recipient_id", sa.String(128), nullable=False),
        sa.Column(
            "recipient_name",
            sa.String().with_variant(LONGTEXT(), "mysql", "mariadb"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("note", sa.String().with_variant(LONGTEXT(), "mysql", "mariadb"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("reviewed_at", sa.Double(), nullable=True),
        sa.Column("reviewer_id", sa.String(128), nullable=True),
        sa.Column(
            "reviewer_name", sa.String().with_variant(LONGTEXT(), "mysql", "mariadb"), nullable=True
        ),
    )
    for field in ("user_id", "recipient_id", "status"):
        op.create_index(f"ix_payment_reports_{field}", "payment_reports", [field])


def downgrade():
    op.drop_table("payment_reports")
