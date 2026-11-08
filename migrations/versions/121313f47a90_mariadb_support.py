"""MariaDB baseline; SQLite retains its existing schema and data."""

from alembic import op

revision = "121313f47a90"
down_revision = "111312e3698f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    if op.get_bind().dialect.name == "mariadb":
        raise RuntimeError("MariaDB cannot downgrade to SQLite-only revisions")
