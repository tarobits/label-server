"""Requester cartridge authorization, rechecked at physical dispatch boundaries."""

from sqlalchemy.orm import Session

from app.authn.auth import actor_for_user
from app.models import Cartridge, PrintJob, User


def can_use_cartridge(session: Session, job: PrintJob, cartridge: Cartridge) -> bool:
    user = session.get(User, job.owner_id)
    if user is None or user.disabled:
        return False
    if job.template_snapshot.get("retry", {}).get("mode") == "free":
        from app.printing.retry_funding import retry_authorization

        return retry_authorization(session, job, cartridge) is not None
    actor = actor_for_user(session, user)
    return actor.is_admin or "cartridge.use" in actor.cartridge_permissions.get(cartridge.id, ())
