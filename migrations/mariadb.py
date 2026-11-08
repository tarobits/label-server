"""Frozen initial MariaDB schema; historical SQLite migrations remain unchanged."""

import json
from pathlib import Path

from sqlalchemy import Connection, inspect, text

BASELINE = "121313f47a90"


def initialize(connection: Connection, *, seed: bool = True) -> None:
    tables = inspect(connection).get_table_names()
    if tables:
        if "alembic_version" not in tables:
            raise RuntimeError(
                "MariaDB schema is not empty and has no Alembic version; use a new empty database"
            )
        return
    root = Path(__file__).resolve().parent
    for statement in (root / "mariadb_baseline.sql").read_text().split(";\n"):
        if statement.strip():
            connection.exec_driver_sql(statement.strip())
    if seed:
        seeds = json.loads((root / "mariadb_seed.json").read_text())
        for table, rows in seeds.items():
            columns = list(rows[0])
            connection.execute(
                text(
                    f"INSERT INTO `{table}` ({', '.join('`' + key + '`' for key in columns)}) "
                    f"VALUES ({', '.join(':' + key for key in columns)})"
                ),
                rows,
            )
    connection.exec_driver_sql(
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY) ENGINE=InnoDB"
    )
    connection.execute(
        text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": BASELINE}
    )
    connection.commit()
