"""Allow tape profiles to be retired from new submissions without deleting history.

Revision ID: 34df80b7a621
Revises: 20201b1c52b8
"""

import sqlalchemy as sa
from alembic import op

revision = "34df80b7a621"
down_revision = "20201b1c52b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tape_profiles", sa.Column("available", sa.Boolean(), nullable=False, server_default="1")
    )


def downgrade():
    op.drop_column("tape_profiles", "available")
