"""Allow printers to permanently opt out of automatic printing."""

import sqlalchemy as sa
from alembic import op

revision = "19191a0b41a7"
down_revision = "181819fa30f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "printers",
        sa.Column("no_automatic_printing", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("printers", "no_automatic_printing")
