"""Remember each account's last visited application version."""

import sqlalchemy as sa
from alembic import op

revision = "da73b8c19e42"
down_revision = "f281d7b4a906"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_version", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_seen_version")
