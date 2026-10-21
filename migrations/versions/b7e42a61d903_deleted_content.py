"""Hold deleted accounts and content for restoration for 30 days.

Revision ID: b7e42a61d903
Revises: c91d8e5a206b
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e42a61d903"
down_revision = "c91d8e5a206b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "deleted_content",
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("identifier", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("deleted_by", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.Double(), nullable=False),
        sa.Column("purge_after", sa.Double(), nullable=False),
        sa.Column("purged_at", sa.Double(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_deleted_content_purge_after", "deleted_content", ["purge_after"])
    op.create_index("ix_deleted_content_account_id", "deleted_content", ["account_id"])


def downgrade():
    op.drop_table("deleted_content")
