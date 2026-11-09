"""Retain the software version last reported by each companion."""

import sqlalchemy as sa
from alembic import op

revision = "171718e92fe5"
down_revision = "161617d81ed4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companions", sa.Column("software_version", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("companions", "software_version")
