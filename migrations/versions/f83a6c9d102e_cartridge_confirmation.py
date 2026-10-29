"""Record explicit confirmation of installed cartridge detection mismatches."""

import sqlalchemy as sa
from alembic import op

revision = "f83a6c9d102e"
down_revision = "e72f5b3a8109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("printer_state", sa.Column("media_confirmation", sa.JSON(), nullable=True))
    op.add_column(
        "printer_state", sa.Column("media_verified_fingerprint", sa.String(), nullable=True)
    )
    op.add_column(
        "printer_state",
        sa.Column("cartridge_check_enabled", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.add_column(
        "printer_state",
        sa.Column("cartridge_check_pending", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("printer_state", "cartridge_check_pending")
    op.drop_column("printer_state", "cartridge_check_enabled")
    op.drop_column("printer_state", "media_verified_fingerprint")
    op.drop_column("printer_state", "media_confirmation")
