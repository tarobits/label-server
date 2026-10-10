from alembic import context

from app import job_access_models, request_models  # noqa: F401
from app.config import Settings
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
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
