"""Keep retired cartridges available to historical usage and review."""

import sqlalchemy as sa
from alembic import op

revision = "a18d6c93b204"
down_revision = "f83a6c9d102e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cartridges", sa.Column("archived", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("cartridges", "archived")
