"""Validate or copy a stopped SQLite installation into an empty MariaDB database.

Credentials are read from a private environment file, never command-line URLs.
The source is opened read-only and is not changed or switched automatically.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.engine import make_url

from app.binary_json import check_packet_size, encode_binary
from app.database_lock import database_owner, lock_name
from app.db import make_engine

ROOT = Path(__file__).resolve().parents[1]


class MigrationError(Exception):
    pass


def head_revision() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


def target_url(path: Path) -> str:
    value = dotenv_values(path, interpolate=False).get("LABEL_DATABASE_URL")
    if not value or make_url(value).drivername != "mariadb+pymysql":
        raise MigrationError("The target file must set LABEL_DATABASE_URL to a mariadb+pymysql URL")
    return value


@contextmanager
def stopped_source(path: Path) -> Generator[sqlite3.Connection, None, None]:
    path = path.resolve(strict=True)
    with path.with_suffix(".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MigrationError("Stop the main server before migration") from None
        source = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
        try:
            source.execute("BEGIN")
            if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise MigrationError(
                    "SQLite integrity check failed; restore a healthy backup first"
                )
            if source.execute("PRAGMA foreign_key_check").fetchone():
                raise MigrationError(
                    "SQLite contains broken foreign keys; repair them before migration"
                )
            revisions = source.execute("SELECT version_num FROM alembic_version").fetchall()
            if revisions != [(head_revision(),)]:
                raise MigrationError("Upgrade the SQLite database to this release before migrating")
            if not source.execute(
                "SELECT 1 FROM asset_imports WHERE id='legacy-files-v1'"
            ).fetchone():
                raise MigrationError(
                    "Import local assets first: start this release once or run scripts/migrate_assets.py before database migration"
                )
            for table in ("batches", "label_copies"):
                if source.execute(
                    f"SELECT 1 FROM {table} WHERE state='PRINTING' LIMIT 1"
                ).fetchone():
                    raise MigrationError(
                        "Printing is still in progress; settle or review it before migration"
                    )
            if source.execute(
                "SELECT 1 FROM companion_batches WHERE go_token IS NOT NULL AND result IS NULL LIMIT 1"
            ).fetchone():
                raise MigrationError(
                    "A companion batch is unsettled; reconnect and settle it before migration"
                )
            yield source
        finally:
            source.close()


def schema_tables(source: sqlite3.Connection) -> dict[str, list[str]]:
    from app import (  # noqa: F401
        billing_models,
        job_access_models,
        queue_routing_models,
        request_models,
    )
    from app.models import Base

    actual = {
        row[0]
        for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    expected = set(Base.metadata.tables) | {"alembic_version"}
    if actual != expected:
        raise MigrationError(
            "SQLite tables do not match this release; migration would omit or invent data"
        )
    result = {}
    for table in Base.metadata.sorted_tables:
        columns = [c[1] for c in source.execute(f'PRAGMA table_info("{table.name}")')]
        if set(columns) != set(table.c.keys()):
            raise MigrationError(f"Column mismatch in {table.name}")
        result[table.name] = sorted(columns)
        for column in table.c:
            length = getattr(column.type, "length", None)
            if (
                length
                and source.execute(
                    f'SELECT 1 FROM "{table.name}" WHERE length("{column.name}") > ? LIMIT 1',
                    (length,),
                ).fetchone()
            ):
                raise MigrationError(
                    f"A value in {table.name}.{column.name} exceeds the MariaDB column limit"
                )
    return result


def require_empty_target(connection: Connection, tables: dict[str, list[str]]) -> None:
    inspector = inspect(connection)
    actual = set(inspector.get_table_names())
    if not actual:
        return
    if actual != set(tables) | {"alembic_version"}:
        raise MigrationError("Target must be empty or an empty schema created by this migration")
    engines = connection.exec_driver_sql(
        "SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
    ).fetchall()
    if any(row[0] != "InnoDB" for row in engines):
        raise MigrationError("Every target table must use transactional InnoDB storage")
    if connection.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall() != [
        (head_revision(),)
    ]:
        raise MigrationError("Target schema revision does not match this release")
    for table, columns in tables.items():
        if set(columns) != {c["name"] for c in inspector.get_columns(table)}:
            raise MigrationError(f"Target column mismatch in {table}")
        if connection.exec_driver_sql(f"SELECT 1 FROM `{table}` LIMIT 1").first():
            raise MigrationError("Target contains application data; nothing will be overwritten")


def digest(rows: Any) -> tuple[int, str]:
    checksum = hashlib.sha256()
    count = 0
    for row in rows:
        checksum.update(
            json.dumps(
                list(row),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
                default=encode_binary,
            ).encode()
        )
        checksum.update(b"\n")
        count += 1
    return count, checksum.hexdigest()


def copy_rows(
    source: sqlite3.Connection, connection: Connection, tables: dict[str, list[str]]
) -> dict[str, int]:
    from app.models import Base

    counts = {}
    # Self-referencing locations need not be stored parent-first in SQLite.
    # Re-enable checks AND explicitly validate every FK before committing.
    connection.exec_driver_sql("SET SESSION FOREIGN_KEY_CHECKS=0")
    try:
        for table, columns in tables.items():
            column_sql = ", ".join(f"`{c}`" for c in columns)
            cursor = source.execute(f"SELECT {column_sql} FROM `{table}`")
            while rows := cursor.fetchmany(1 if table == "stored_assets" else 200):
                sql = f"INSERT INTO `{table}` ({column_sql}) VALUES ({', '.join(['%s'] * len(columns))})"
                if any(isinstance(value, bytes) for row in rows for value in row):
                    for row in rows:
                        connection.exec_driver_sql(sql, row)
                else:
                    connection.exec_driver_sql(sql, rows)
            order = ", ".join(f"`{c.name}`" for c in Base.metadata.tables[table].primary_key)
            query = f"SELECT {column_sql} FROM `{table}` ORDER BY {order}"
            before = digest(source.execute(query))
            after = digest(connection.exec_driver_sql(query))
            if before != after:
                raise MigrationError(
                    f"Verification failed for {table}; the copy will be rolled back"
                )
            counts[table] = before[0]
        inspector = inspect(connection)
        for table in tables:
            for foreign_key in inspector.get_foreign_keys(table):
                local, remote = foreign_key["constrained_columns"], foreign_key["referred_columns"]
                joined = " AND ".join(
                    f"c.`{a}` = p.`{b}`" for a, b in zip(local, remote, strict=True)
                )
                present = " AND ".join(f"c.`{a}` IS NOT NULL" for a in local)
                if connection.exec_driver_sql(
                    f"SELECT 1 FROM `{table}` c LEFT JOIN `{foreign_key['referred_table']}` p ON {joined} WHERE {present} AND p.`{remote[0]}` IS NULL LIMIT 1"
                ).first():
                    raise MigrationError(f"Foreign-key verification failed for {table}")
        return counts
    finally:
        connection.exec_driver_sql("SET SESSION FOREIGN_KEY_CHECKS=1")


def migrate(source_path: Path, engine: Engine, *, apply: bool, backup_dir: Path) -> dict[str, int]:
    if engine.dialect.name != "mariadb":
        raise MigrationError("The destination must be MariaDB")
    with stopped_source(source_path) as source, database_owner(engine, enforce=True):
        tables = schema_tables(source)
        with engine.connect() as connection:
            require_empty_target(connection, tables)
            packet_limit = int(
                connection.exec_driver_sql("SELECT @@max_allowed_packet").scalar_one()
            )
            try:
                for row in source.execute("SELECT content, source, details FROM stored_assets"):
                    check_packet_size(row, packet_limit)
            except ValueError as error:
                raise MigrationError(str(error)) from error
            owner = connection.scalar(
                text("SELECT IS_USED_LOCK(:name)"), {"name": lock_name(engine)}
            )
        if not apply:
            return {
                table: source.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]
                for table in tables
            }
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup = backup_dir / (
            datetime.now(UTC).strftime("sqlite-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8] + ".db"
        )
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        with sqlite3.connect(backup) as snapshot:
            source.backup(snapshot)
        print(f"SQLite backup: {backup}")
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.attributes.update(
            database_url=engine.url.render_as_string(hide_password=False),
            seed=False,
            database_owner=owner,
        )
        command.upgrade(config, "head")
        with engine.begin() as connection:
            require_empty_target(connection, tables)
            return copy_rows(source, connection, tables)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing SQLite database file")
    parser.add_argument(
        "--target-env-file",
        type=Path,
        required=True,
        help="Private file containing the target LABEL_DATABASE_URL",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Copy and verify; default only checks readiness"
    )
    parser.add_argument("--backup-dir", type=Path, default=Path("database-migration-backups"))
    args = parser.parse_args()
    engine = None
    try:
        engine = make_engine(target_url(args.target_env_file))
        counts = migrate(args.source, engine, apply=args.apply, backup_dir=args.backup_dir)
        print(
            f"{'Copied and verified' if args.apply else 'Ready to copy'} {sum(counts.values())} rows across {len(counts)} tables."
        )
        if args.apply:
            print(
                "SQLite and deployment configuration are unchanged. Keep the same local data directory when switching LABEL_DATABASE_URL."
            )
        return 0
    except MigrationError as error:
        print(f"Migration stopped: {error}", file=sys.stderr)
    except Exception as error:
        # DBAPI messages can contain credentials, row contents, or usernames.
        print(
            f"Migration stopped ({type(error).__name__}). Check database connectivity, permissions, and schema. No credentials or row contents are printed.",
            file=sys.stderr,
        )
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
