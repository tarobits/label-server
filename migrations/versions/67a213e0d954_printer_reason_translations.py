"""Preserve translation metadata for new printer block reasons."""

import sqlalchemy as sa
from alembic import op

revision = "67a213e0d954"
down_revision = "56f102d9c843"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("printer_state", sa.Column("blocker_translation", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("printer_state", "blocker_translation")
