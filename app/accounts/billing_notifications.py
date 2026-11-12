"""Private group notifications never route to shared operational endpoints."""

from sqlalchemy.orm import Session

from app.accounts.billing import can_decide, can_read_request
from app.accounts.billing_models import BillingRequest
from app.authn.access import Actor
from app.models import Notification


def visible(session: Session, actor: Actor, notice: Notification) -> bool:
    identifier = notice.context.get("billing_request_id")
    if not identifier:
        return True
    request = session.get(BillingRequest, identifier)
    if request is None or notice.recipient_id != actor.id:
        return False
    if notice.context.get("billing_actionable"):
        return request.status == "pending" and can_decide(session, actor, request)
    return can_read_request(session, actor, request)
