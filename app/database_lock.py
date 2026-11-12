"""One main-server owner per database, including when MariaDB is on another host."""

import hashlib
from collections.abc import Callable
from contextlib import contextmanager
from threading import Event, Thread
from typing import Any, Generator

from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.exc import SQLAlchemyError


def lock_name(engine: Engine) -> str:
    return "label-room:" + hashlib.sha256((engine.url.database or "").encode()).hexdigest()[:40]


@contextmanager
def database_owner(
    engine: Engine,
    *,
    enforce: bool = False,
    expected_owner: int | None = None,
    on_loss: Callable[[], None] | None = None,
) -> Generator[None, None, None]:
    if engine.dialect.name != "mariadb":
        yield
        return
    name = lock_name(engine)
    connection: Connection | None = None
    installed = False
    owner_id = expected_owner or 0
    stopped, lost = Event(), Event()
    heartbeat: Thread | None = None

    def ownership_lost() -> None:
        lost.set()
        if on_loss:
            on_loss()

    def check_owner(dbapi: Any, record: Any, proxy: Any) -> None:
        if lost.is_set():
            raise RuntimeError("Database ownership was lost; stop this server and investigate")
        cursor = None
        try:
            cursor = dbapi.cursor()
            cursor.execute("SELECT IS_USED_LOCK(%s)", (name,))
            if cursor.fetchone()[0] != owner_id:
                raise RuntimeError("Database ownership was lost; stop this server and investigate")
        except Exception:
            ownership_lost()
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def before_execute(
        conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        check_owner(conn.connection.dbapi_connection, None, None)

    def before_commit(conn: Connection) -> None:
        check_owner(conn.connection.dbapi_connection, None, None)

    try:
        if expected_owner is None:
            connection = engine.connect()
            if connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": name}) != 1:
                raise RuntimeError("Another server or maintenance operation owns this database")
            owner_id = int(connection.scalar(text("SELECT CONNECTION_ID()")) or 0)
            connection.exec_driver_sql("SET SESSION wait_timeout=600")
            connection.commit()
        if enforce:
            event.listen(engine, "checkout", check_owner)
            event.listen(engine, "before_cursor_execute", before_execute)
            event.listen(engine, "commit", before_commit)
            installed = True
        if connection is not None:

            def keep_alive() -> None:
                assert connection is not None
                while not stopped.wait(30):
                    try:
                        connection.exec_driver_sql("SELECT 1")
                        connection.commit()
                    except Exception:
                        ownership_lost()
                        return

            heartbeat = Thread(target=keep_alive, name="database-owner", daemon=True)
            heartbeat.start()
        yield
    finally:
        stopped.set()
        if heartbeat is not None:
            heartbeat.join()
        if installed:
            event.remove(engine, "checkout", check_owner)
            event.remove(engine, "before_cursor_execute", before_execute)
            event.remove(engine, "commit", before_commit)
        if connection is not None:
            try:
                if owner_id and not connection.invalidated:
                    connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
                    connection.commit()
            except SQLAlchemyError:
                # A lost connection has already released its server-side lock.
                # Never reconnect here and conceal the original operation failure.
                connection.invalidate()
            finally:
                connection.close()
