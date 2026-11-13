"""One durable release gate shared by local and remote dispatch."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.i18n import Message
from app.models import ReleaseMigration


def migration_pending(session: Session) -> bool:
    from app.maintenance.relationship_migration import pending

    migration = session.get(ReleaseMigration, "0.13.0")
    return bool(migration is not None and migration.completed_at is None) or pending(session)


def require_migration_complete(session: Session) -> None:
    if migration_pending(session):
        raise HTTPException(
            409,
            Message("serverMessages.printingIsPausedUntilAnAdministratorCompletesThe0130Migration"),
        )
