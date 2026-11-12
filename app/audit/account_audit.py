"""Account evidence deliberately excludes credentials and recovery destinations."""

import time

from sqlalchemy.orm import Session

from app.audit.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.models import User, new_id


def record_account(
    session: Session,
    action: str,
    user: User | None,
    *,
    system: bool = False,
    configured: bool | None = None,
) -> None:
    fields = {
        "source": AuditField("system" if system else "user" if user else "anonymous", ()),
        "actor_id": AuditField(user.id if user and not system else None, ()),
        "actor_name": AuditField(user.username if user and not system else None, ()),
        "victim_ids": AuditField([user.id] if user else [], ()),
        "victim_names": AuditField([user.username] if user else [], ()),
    }
    if configured is not None:
        fields["configured"] = (
            AuditField(configured, (AuditRequirement("account", user.id, "account.self"),))
            if user
            else AuditField(configured, (AuditRequirement("application", "", "audit.view_all"),))
        )
    append_audit(
        session,
        event_id=new_id(),
        action=action,
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global"),),
        fields=fields,
    )
