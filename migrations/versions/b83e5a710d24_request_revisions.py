"""Version pending requests to reject approval of outdated copies."""

import sqlalchemy as sa
from alembic import op

revision = "b83e5a710d24"
down_revision = "a62d94f07b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_requests", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )


def downgrade() -> None:
    op.drop_column("print_requests", "revision")
