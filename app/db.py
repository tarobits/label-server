from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.drivername == "mariadb+pymysql":
        if not parsed.database or parsed.query.get("charset", "utf8mb4") != "utf8mb4":
            raise ValueError("MariaDB requires a database name and utf8mb4 charset")
        engine = create_engine(
            parsed.update_query_dict({"charset": "utf8mb4"}),
            pool_pre_ping=True,
            pool_recycle=1800,
            hide_parameters=True,
            isolation_level="READ COMMITTED",
            connect_args={"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30},
        )

        @event.listens_for(engine, "connect")
        def configure_mariadb(connection: object, _: object) -> None:
            cursor = connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            if "MariaDB" not in version or tuple(
                int(v) for v in version.split("-")[0].split(".")[:2]
            ) < (10, 11):
                raise ValueError("MariaDB 10.11 or newer is required")
            cursor.execute(
                "SET SESSION sql_mode='STRICT_ALL_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
            )
            cursor.close()

        return engine
    if not parsed.drivername.startswith("sqlite"):
        raise ValueError("Use a SQLite or mariadb+pymysql database URL")
    if parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30}, hide_parameters=True
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection: object, _: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def begin_write(session: Session) -> None:
    """Call under the process mutation lock; MariaDB ownership excludes other servers."""
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    else:
        session.begin()
