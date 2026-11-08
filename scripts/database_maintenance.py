"""Private updater bridge: hold MariaDB ownership while backing up or restoring.

Commands and replies use stdin/stdout JSON. No database URL or row contents are
sent to the updater. Backups contain sensitive application data and are mode 0600.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Connection, inspect

from app.config import Settings
from app.database_lock import database_owner
from app.db import make_engine


def encode(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def backup(connection: Connection, path: Path) -> None:
    from app import job_access_models, queue_routing_models, request_models  # noqa: F401
    from app.models import Base

    tables = inspect(connection).get_table_names()
    if set(tables) != set(Base.metadata.tables) | {"alembic_version"}:
        raise ValueError("Use a dedicated application database with the expected schema")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as output:
        output.write(
            encode({"schema": 1, "database": connection.engine.url.database, "tables": tables})
        )
        for table in tables:
            quoted = connection.dialect.identifier_preparer.quote(table)
            definition = connection.exec_driver_sql(f"SHOW CREATE TABLE {quoted}").one()[1]
            result = connection.exec_driver_sql(f"SELECT * FROM {quoted}")
            output.write(
                encode({"table": table, "create": definition, "columns": list(result.keys())})
            )
            checksum, count = hashlib.sha256(), 0
            for row in result:
                line = encode({"row": list(row)})
                checksum.update(line)
                output.write(line)
                count += 1
            output.write(encode({"end": table, "count": count, "sha256": checksum.hexdigest()}))
        output.write(encode({"complete": True}))


def records(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rb") as archive:
        for line in archive:
            yield json.loads(line)


def validate(path: Path, database: str | None) -> None:
    stream = records(path)
    header = next(stream)
    if header.get("schema") != 1 or header.get("database") != database:
        raise ValueError("Backup database or format mismatch")
    for table in header["tables"]:
        definition = next(stream)
        if (
            definition.get("table") != table
            or not definition.get("create")
            or not definition.get("columns")
        ):
            raise ValueError("Incomplete backup schema")
        checksum, count = hashlib.sha256(), 0
        for record in stream:
            if "row" not in record:
                if record != {"end": table, "count": count, "sha256": checksum.hexdigest()}:
                    raise ValueError("Backup checksum mismatch")
                break
            if len(record["row"]) != len(definition["columns"]):
                raise ValueError("Backup column mismatch")
            checksum.update(encode(record))
            count += 1
        else:
            raise ValueError("Truncated backup")
    if next(stream) != {"complete": True} or next(stream, None) is not None:
        raise ValueError("Incomplete backup")


def restore(connection: Connection, path: Path) -> None:
    # MariaDB DDL commits implicitly. Validate the whole archive before dropping
    # anything; failures after that point must leave the application stopped.
    validate(path, connection.engine.url.database)
    quote = connection.dialect.identifier_preparer.quote
    connection.exec_driver_sql("SET SESSION FOREIGN_KEY_CHECKS=0")
    try:
        for table in inspect(connection).get_table_names():
            connection.exec_driver_sql(f"DROP TABLE {quote(table)}")
        stream = records(path)
        next(stream)
        sql: str | None = None
        for item in stream:
            if "table" in item:
                connection.exec_driver_sql(item["create"])
                sql = f"INSERT INTO {quote(item['table'])} ({', '.join(quote(c) for c in item['columns'])}) VALUES ({', '.join(['%s'] * len(item['columns']))})"
            elif "row" in item:
                if sql is None:
                    raise ValueError("Backup row has no table definition")
                connection.exec_driver_sql(sql, tuple(item["row"]))
        connection.commit()
    finally:
        connection.exec_driver_sql("SET SESSION FOREIGN_KEY_CHECKS=1")
        connection.commit()


def reply(value: dict[str, Any]) -> None:
    print(json.dumps(value), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--backup", type=Path, help="Back up a stopped MariaDB installation")
    operation.add_argument(
        "--restore", type=Path, help="Replace the stopped installation's database from its backup"
    )
    args = parser.parse_args()
    engine = None
    try:
        engine = make_engine(Settings().database_url)
        if engine.dialect.name != "mariadb":
            raise ValueError("MariaDB required")
        with database_owner(engine, enforce=True), engine.connect() as connection:
            if args.backup or args.restore:
                if args.backup:
                    backup(connection, args.backup)
                else:
                    restore(connection, args.restore)
                connection.commit()
                print("Database backup completed." if args.backup else "Database restored.")
                return 0
            # ID of the separate ownership connection, for the migration subprocess.
            from sqlalchemy import text

            from app.database_lock import lock_name

            owner = connection.scalar(
                text("SELECT IS_USED_LOCK(:name)"), {"name": lock_name(engine)}
            )
            connection.commit()
            reply({"ready": True, "owner": owner})
            for line in sys.stdin:
                action = json.loads(line)
                if action["action"] == "close":
                    break
                path = Path(action["path"])
                if action["action"] == "backup":
                    backup(connection, path)
                elif action["action"] == "restore":
                    restore(connection, path)
                else:
                    raise ValueError("Unknown action")
                connection.commit()
                reply({"ok": True})
        return 0
    except Exception as error:
        reply({"error": type(error).__name__})
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
