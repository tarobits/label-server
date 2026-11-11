"""Frozen relationship migration contract. Do not change after release.

Dirty installations enter a repair gate; no references are silently rewritten.
SQLite table reconstruction runs in one explicit transaction on an isolated
maintenance connection. Runtime connections always retain foreign_keys=ON.
"""

import time
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection

VERSION = "relationships-v1"
# table, column, parent table, ON DELETE policy
ADDITIONS = (
    ("locations", "owner_id", "users", None),
    ("cartridges", "owner_id", "users", None),
    ("printers", "owner_id", "users", None),
    ("companions", "bound_user_id", "users", None),
    ("companion_pins", "user_id", "users", "CASCADE"),
    ("companion_sessions", "user_id", "users", "CASCADE"),
    ("printer_state", "printer_id", "printers", None),
    ("printer_state", "empty_alert_cartridge_id", "cartridges", "SET NULL"),
    ("batches", "printer_id", "printers", None),
    ("flush_requests", "printer_id", "printers", None),
    ("print_runs", "assigned_printer_id", "printers", None),
    ("label_templates", "group_id", "user_groups", None),
    ("price_quotes", "user_id", "users", "CASCADE"),
    ("notification_reads", "user_id", "users", "CASCADE"),
)


def relationships(connection: Connection) -> list[dict[str, Any]]:
    """Include existing constraints so earlier corruption is repairable too."""
    inspector = sa.inspect(connection)
    result = {}
    for table in inspector.get_table_names():
        for fk in inspector.get_foreign_keys(table):
            columns = fk["constrained_columns"]
            if len(columns) != 1 or len(fk["referred_columns"]) != 1:
                raise RuntimeError("Relationship migration requires review of composite keys")
            column = columns[0]
            result[(table, column)] = {
                "table": table,
                "column": column,
                "parent": fk["referred_table"],
                "parent_column": fk["referred_columns"][0],
            }
    for table, column, parent, _ in ADDITIONS:
        result[(table, column)] = {
            "table": table,
            "column": column,
            "parent": parent,
            "parent_column": "id",
        }
    return sorted(result.values(), key=lambda item: (item["table"], item["column"]))


def orphan_query(connection: Connection, relation: dict[str, Any]) -> tuple[sa.Table, Any]:
    metadata = sa.MetaData()
    child = sa.Table(relation["table"], metadata, autoload_with=connection, resolve_fks=False)
    parent = metadata.tables.get(relation["parent"])
    if parent is None:
        parent = sa.Table(relation["parent"], metadata, autoload_with=connection, resolve_fks=False)
    target = parent.alias("relationship_parent")
    column = child.c[relation["column"]]
    condition = column.is_not(None) & ~sa.exists(
        sa.select(1).select_from(target).where(target.c[relation["parent_column"]] == column)
    )
    return child, condition


def violations(connection: Connection) -> list[dict[str, Any]]:
    problems = []
    for relation in relationships(connection):
        child, condition = orphan_query(connection, relation)
        count = connection.scalar(sa.select(sa.func.count()).select_from(child).where(condition))
        if count:
            problems.append({**relation, "count": count})
    return problems


def require_clean(connection: Connection) -> None:
    problems = violations(connection)
    if problems:
        detail = ", ".join(f"{p['table']}.{p['column']}: {p['count']}" for p in problems)
        raise RuntimeError(
            f"Repair orphaned references in the administrator migration screen: {detail}"
        )


def install(connection: Connection) -> None:
    """Idempotent for MariaDB's implicit DDL commits and interrupted restarts."""
    require_clean(connection)  # Check every relationship before the first DDL statement.
    operations = Operations(MigrationContext.configure(connection))
    grouped: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    for table, column, parent, policy in ADDITIONS:
        existing = sa.inspect(connection).get_foreign_keys(table)
        if not any(fk["constrained_columns"] == [column] for fk in existing):
            grouped[table].append((column, parent, policy))
    for table, additions in grouped.items():
        columns = {c["name"]: c for c in sa.inspect(connection).get_columns(table)}
        with operations.batch_alter_table(table) as batch:
            for column, parent, policy in additions:
                if getattr(columns[column]["type"], "length", None) != 128:
                    batch.alter_column(
                        column,
                        type_=sa.String(128),
                        existing_type=columns[column]["type"],
                        existing_nullable=columns[column]["nullable"],
                    )
                batch.create_foreign_key(
                    f"fk_{table}_{column}", parent, [column], ["id"], ondelete=policy
                )
    require_clean(connection)


def finalize(connection: Connection, *, alembic_autocommit: bool = False) -> None:
    """Only call before serving requests, with exclusive deployment ownership."""
    sqlite = connection.dialect.name == "sqlite"
    if not alembic_autocommit:
        connection.commit()
    try:
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        install(connection)
        if sqlite and connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("Foreign key validation failed; migration rolled back")
        connection.execute(
            sa.text("UPDATE release_migrations SET completed_at=:now WHERE version=:version"),
            {"now": time.time(), "version": VERSION},
        )
        if sqlite:
            connection.exec_driver_sql("COMMIT")
        if not alembic_autocommit:
            connection.commit()
    except BaseException:
        if sqlite:
            connection.exec_driver_sql("ROLLBACK")
        if not alembic_autocommit:
            connection.rollback()
        raise
    finally:
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            if connection.scalar(sa.text("PRAGMA foreign_keys")) != 1:
                raise RuntimeError("Could not restore SQLite foreign key enforcement")
            if not alembic_autocommit:
                connection.commit()
