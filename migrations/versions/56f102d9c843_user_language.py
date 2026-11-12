"""Account language preferences for interfaces and asynchronous notifications.

Revision ID: 56f102d9c843
Revises: 45e091c8b732
"""

import sqlalchemy as sa
from alembic import op

revision = "56f102d9c843"
down_revision = "45e091c8b732"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("language", sa.String(16), nullable=False, server_default="browser")
    )
    op.add_column(
        "users", sa.Column("browser_language", sa.String(16), nullable=False, server_default="en")
    )


def downgrade():
    op.drop_column("users", "browser_language")
    op.drop_column("users", "language")
