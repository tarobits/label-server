import os
from contextlib import nullcontext

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app import job_access_models, queue_routing_models, request_models  # noqa: F401
from app.config import Settings
from app.database_lock import database_owner
from app.db import make_engine
from app.models import Base

config = context.config
url = config.attributes.get("database_url", Settings().database_url)

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url)
    external_owner = config.attributes.get("database_owner") or os.environ.get(
        "LABEL_DATABASE_MAINTENANCE_OWNER"
    )
    ownership = (
        database_owner(
            engine, enforce=True, expected_owner=int(external_owner) if external_owner else None
        )
        if engine.dialect.name == "mariadb"
        else nullcontext()
    )
    with ownership, engine.connect() as connection:
        if engine.dialect.name == "mariadb":
            from migrations.mariadb import BASELINE, initialize

            # A new MariaDB deployment starts at the first portable release. Never
            # replay SQLite-specific history or stamp evolving ORM metadata as current.
            directory = ScriptDirectory.from_config(config)
            allowed = {r.revision for r in directory.iterate_revisions("heads", BASELINE)} | {
                BASELINE
            }
            if not inspect(connection).get_table_names():
                try:
                    requested = context.get_revision_argument()
                except KeyError:
                    raise RuntimeError(
                        "Initialize the empty MariaDB database with alembic upgrade head"
                    ) from None
                if requested is None or any(
                    r.revision not in allowed for r in directory.get_revisions(requested)
                ):
                    raise RuntimeError("MariaDB requires the initial MariaDB revision or newer")
                initialize(connection, seed=config.attributes.get("seed", True))
            if connection.scalar(text("SELECT version_num FROM alembic_version")) not in allowed:
                raise RuntimeError("Unsupported MariaDB schema revision")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=engine.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
