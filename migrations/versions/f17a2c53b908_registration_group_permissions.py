"""Store template-group collaboration permissions on registration codes."""

import sqlalchemy as sa
from alembic import op

revision = "f17a2c53b908"
down_revision = "b7e42a61d903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "registration_codes",
        sa.Column("group_permissions", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("registration_codes", "group_permissions")
