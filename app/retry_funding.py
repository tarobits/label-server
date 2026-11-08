"""Retry consent and live checks; independent of physical printer protocols."""

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.auth import actor_for_user
from app.models import Batch, Cartridge, PrintJob, RetryOffer, User
from app.use_overrides import authorization_valid


def retry_authorization(
    session: Session, job: PrintJob, cartridge: Cartridge
) -> dict[str, Any] | None:
    retry = job.template_snapshot.get("retry", {})
    if retry.get("mode") != "free" or not retry_eligible(session, job):
        return None
    authorization = {
        "actor_id": retry["actor_id"],
        "actor_name": retry["actor_name"],
        "cartridge_id": retry["cartridge_id"],
        "kind": "free_retry",
        "offer_id": retry["offer_id"],
    }
    return authorization if authorization_valid(session, authorization, cartridge) else None


def retry_eligible(session: Session, job: PrintJob) -> bool:
    retry = job.template_snapshot.get("retry")
    if not retry:
        return True
    user = session.get(User, retry.get("actor_id"))
    requester = session.get(User, job.owner_id)
    if not user or user.disabled or not requester or requester.disabled:
        return False
    actor = actor_for_user(session, user)
    permissions = actor.destination_permissions.get(retry["printer_id"], ())
    start = "printer.start_own" if user.id == job.owner_id else "printer.start_any"
    if not (actor.is_admin or start in permissions or "printer.start_any" in permissions):
        return False
    if retry["mode"] == "free":
        cartridge = session.get(Cartridge, retry.get("cartridge_id"))
        return bool(
            cartridge and not cartridge.archived and authorization_valid(session, retry, cartridge)
        )
    return True


def clone_job(session: Session, offer: RetryOffer) -> PrintJob:
    original = session.get(PrintJob, offer.source_job_id)
    batch = session.get(Batch, offer.batch_id)
    assert original is not None and batch is not None
    snapshot = copy.deepcopy(original.template_snapshot)
    snapshot.pop("pricing", None)
    snapshot.pop("print_plan", None)
    retry = {
        "offer_id": offer.id,
        "mode": offer.mode,
        "actor_id": offer.actor_id,
        "actor_name": offer.actor_name,
        "cartridge_id": offer.cartridge_id,
        "printer_id": batch.printer_id,
        "batch_id": batch.id,
        "source_job_id": original.id,
        "source_run_id": original.run_id,
        "copy_ids": offer.copy_ids,
    }
    snapshot["retry"] = retry
    attribution = copy.deepcopy(original.attribution or {})
    attribution["retry_authorization"] = copy.deepcopy(retry)
    return PrintJob(
        destination_id=original.destination_id,
        owner_id=original.owner_id,
        authorization_basis=original.authorization_basis,
        profile_id=original.profile_id,
        template_id=original.template_id,
        template_snapshot=snapshot,
        payload=copy.deepcopy(original.payload),
        width_mm=original.width_mm,
        length_mm=original.length_mm,
        copies=len(offer.copy_ids),
        source_row=original.source_row,
        notify_on_completion=original.notify_on_completion,
        attribution=attribution,
    )
