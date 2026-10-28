"""Preserve whether attempt consumption was estimated, measured or reported."""

import sqlalchemy as sa
from alembic import op

revision = "b37c60e14f92"
down_revision = "a91e2bf0c463"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A short-lived a91 migration included this column. Accept that applied
    # schema as well as the original a91 without changing existing audit values.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("batches")}
    if "consumption_source" not in columns:
        op.add_column("batches", sa.Column("consumption_source", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("batches", "consumption_source")
