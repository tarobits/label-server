"""Record template revision editors, dates, and restore origins."""

import sqlalchemy as sa
from alembic import op

revision = "e92b4f06a318"
down_revision = "da73b8c19e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing history has no reliable editor or save date to backfill.
    op.add_column("template_revisions", sa.Column("created_at", sa.Double(), nullable=True))
    op.add_column("template_revisions", sa.Column("edited_by", sa.JSON(), nullable=True))
    op.add_column(
        "template_revisions", sa.Column("restored_from_revision", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("template_revisions", "restored_from_revision")
    op.drop_column("template_revisions", "edited_by")
    op.drop_column("template_revisions", "created_at")
