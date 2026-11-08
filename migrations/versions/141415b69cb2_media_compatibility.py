"""Controlled media families and fixed-label dimensions on profiles."""

import sqlalchemy as sa
from alembic import op

revision = "141415b69cb2"
down_revision = "131314a58ba1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tape_profiles",
        sa.Column("media_family", sa.String(32), nullable=False, server_default="tze"),
    )
    op.add_column("tape_profiles", sa.Column("label_length_mm", sa.Double(), nullable=True))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM tape_profiles WHERE media_family != 'tze' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Remove non-TZe profiles before downgrading media compatibility")
    op.drop_column("tape_profiles", "label_length_mm")
    op.drop_column("tape_profiles", "media_family")
