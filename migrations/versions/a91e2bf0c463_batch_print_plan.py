"""Preserve physical output and minimum-cut waste estimates for each attempt."""

import sqlalchemy as sa
from alembic import op

revision = "a91e2bf0c463"
down_revision = "e92b4f06a318"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old attempts cannot be reconstructed from current printer settings.
    op.add_column("batches", sa.Column("print_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("batches", "print_plan")
