"""Add public session identifiers and last-seen details."""

import sqlalchemy as sa
from alembic import op

revision = "c94f6b821e35"
down_revision = "b83e5a710d24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("id", sa.String(), nullable=True))
    op.execute("UPDATE auth_sessions SET id = lower(hex(randomblob(16)))")
    with op.batch_alter_table("auth_sessions") as batch:
        batch.alter_column("id", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint("uq_auth_sessions_id", ["id"])
        batch.add_column(sa.Column("last_seen_at", sa.Double(), nullable=True))
        batch.add_column(sa.Column("ip_address", sa.String(), nullable=True))
        batch.add_column(sa.Column("user_agent", sa.String(), nullable=True))
        batch.add_column(sa.Column("location", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_constraint("uq_auth_sessions_id", type_="unique")
        for name in ("id", "last_seen_at", "ip_address", "user_agent", "location"):
            batch.drop_column(name)
