"""Stage relationship repair before enforcing current-resource foreign keys."""

import sqlalchemy as sa
from alembic import op

from migrations.relationships_v1 import ADDITIONS, VERSION, finalize, violations

revision = "20201b1c52b8"
down_revision = "19191a0b41a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Relationship migration requires an online integrity check")
    connection = op.get_bind()
    config = op.get_context().config
    if (config is None or config.attributes.get("seed", True)) and not connection.scalar(
        sa.text("SELECT version FROM release_migrations WHERE version=:version"),
        {"version": VERSION},
    ):
        connection.execute(
            sa.text("INSERT INTO release_migrations (version, draft) VALUES (:version, :draft)"),
            {"version": VERSION, "draft": "{}"},
        )
    if not violations(connection):
        # SQLite's PRAGMA cannot be changed within a transaction. This also
        # commits the gate first, making any interrupted DDL fail closed.
        with op.get_context().autocommit_block():
            finalize(connection, alembic_autocommit=True)


def downgrade() -> None:
    connection = op.get_bind()
    with op.get_context().autocommit_block():
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            for table, column, _, _ in reversed(ADDITIONS):
                name = f"fk_{table}_{column}"
                if any(fk["name"] == name for fk in sa.inspect(connection).get_foreign_keys(table)):
                    with op.batch_alter_table(table) as batch:
                        batch.drop_constraint(name, type_="foreignkey")
                        if (table, column) in (
                            ("companion_sessions", "user_id"),
                            ("price_quotes", "user_id"),
                        ):
                            from sqlalchemy.dialects.mysql import LONGTEXT

                            batch.alter_column(
                                column,
                                type_=sa.String().with_variant(LONGTEXT(), "mysql", "mariadb"),
                            )
            connection.execute(
                sa.text("DELETE FROM release_migrations WHERE version=:v"), {"v": VERSION}
            )
            if sqlite:
                connection.exec_driver_sql("COMMIT")
        except BaseException:
            if sqlite:
                connection.exec_driver_sql("ROLLBACK")
            raise
        finally:
            if sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
