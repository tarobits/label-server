"""History filtering uses frozen attribution rather than live user permissions."""

from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.access import access_context
from app.activity_redaction import personal_attribution
from app.authorization import visible_destinations
from app.models import Batch, BatchItem, Cartridge, LabelCopy, PrinterDevice, PrintJob, State


def visible_items(request: Request, session: Session) -> Select[BatchItem]:
    query = select(BatchItem).join(Batch).join(LabelCopy).join(PrintJob)
    context = access_context(request)
    if not context.actor.is_admin:
        query = query.where(
            or_(
                Batch.printer_id.in_(visible_destinations(request, session, "view_activity")),
                PrintJob.owner_id == context.actor.id,
            )
        )
    return query


def full_activity(request: Request, batch: Batch, *, review: bool = False) -> bool:
    context = access_context(request)
    return context.can_printer(batch.printer_id, "view_activity") or (
        review
        and batch.state == State.NEEDS_REVIEW
        and context.can_printer(batch.printer_id, "review")
    )


def readable_batch(request: Request, session: Session, identifier: str) -> Batch:
    batch = session.get(Batch, identifier)
    if batch is None:
        raise HTTPException(404, "Batch not found")
    if (
        not full_activity(request, batch, review=True)
        and session.scalar(
            visible_items(request, session)
            .with_only_columns(BatchItem.copy_id)
            .where(BatchItem.batch_id == identifier)
            .limit(1)
        )
        is None
    ):
        raise HTTPException(403, "This batch is not accessible")
    return batch


def activity_record(
    request: Request, session: Session, batch: Batch, *, review: bool = False
) -> dict[str, Any]:
    from app.http import job_template_name, record
    from app.print_audit import batch_audit

    context = access_context(request)
    full = full_activity(request, batch, review=review)
    jobs = select(PrintJob).join(LabelCopy).join(BatchItem).where(BatchItem.batch_id == batch.id)
    if not full:
        jobs = jobs.where(PrintJob.owner_id == context.actor.id)
    names = list(
        dict.fromkeys(
            job.template_snapshot.get("process_name") or job_template_name(session, job)
            for job in session.scalars(jobs.order_by(BatchItem.position)).unique()
        )
    )
    audit = batch_audit(session, batch, None if full else context.actor.id)
    if full:
        return {**record(batch), **audit, "process_names": names, "redacted": False}
    for entry in audit["attribution_summary"]:
        entry["attribution"] = personal_attribution(context, entry["attribution"])
    outcomes = set(
        session.scalars(
            visible_items(request, session)
            .with_only_columns(BatchItem.outcome)
            .where(BatchItem.batch_id == batch.id)
        )
    )
    state = next(
        (
            value
            for value in (
                State.PRINTING,
                State.NEEDS_REVIEW,
                State.FAILED,
                State.CANCELLED,
                State.PRINTED,
            )
            if value in outcomes
        ),
        batch.state,
    )
    # Never serialize the physical plan, errors, evidence, whole-batch totals or
    # trigger into a personal view. Those can include other users' work.
    return {
        "id": batch.id,
        "printer_id": batch.printer_id if context.can_printer(batch.printer_id, "view") else "",
        "cartridge_id": batch.cartridge_id
        if context.can_cartridge(batch.cartridge_id, "view")
        else "",
        "state": state,
        "created_at": batch.created_at,
        "finished_at": batch.finished_at,
        "estimated_mm": None,
        "consumed_mm": None,
        "consumption_source": None,
        "error": None,
        "shortage_warning": False,
        "print_plan": None,
        "trigger": None,
        "process_names": names,
        "redacted": True,
        "attribution_summary": audit["attribution_summary"],
        "payers": audit["payers"],
    }


def filter_batches(
    query: Select[Batch],
    printer: str | None,
    cartridge: str | None,
    requester: str | None,
    authorizer: str | None,
    items: Select[BatchItem] | None = None,
) -> Select[Batch]:
    if printer:
        query = query.where(Batch.printer_id == printer)
    if cartridge:
        query = query.where(Batch.cartridge_id == cartridge)
    attribution = BatchItem.attribution
    matches = (
        items.with_only_columns(BatchItem.batch_id)
        if items is not None
        else select(BatchItem.batch_id)
    )
    if requester:
        query = query.where(
            Batch.id.in_(matches.where(attribution["requested_by"]["id"].as_string() == requester))
        )
    if authorizer:
        conditions = [
            and_(
                attribution["authorization"]["kind"].as_string().in_(["approval", "override"]),
                attribution["authorization"]["actor"]["id"].as_string() == authorizer,
            ),
            attribution["cartridge_authorization"]["actor_id"].as_string() == authorizer,
            attribution["retry_authorization"]["actor_id"].as_string() == authorizer,
            attribution["release"]["actor"]["id"].as_string() == authorizer,
        ]
        query = query.where(Batch.id.in_(matches.where(or_(*conditions))))
    return query


def authorizers(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    approval = snapshot.get("authorization") or {}
    if approval.get("kind") in {"approval", "override"} and approval.get("actor"):
        result.append(approval["actor"])
    if release := (snapshot.get("release") or {}).get("actor"):
        result.append(release)
    for key in ("cartridge_authorization", "retry_authorization"):
        if actor := snapshot.get(key):
            result.append({"id": actor["actor_id"], "name": actor["actor_name"]})
    return result


def filter_options(
    session: Session, query: Select[Batch], items: Select[BatchItem] | None = None
) -> dict[str, Any]:
    ids = query.with_only_columns(Batch.id)
    printers = dict(
        session.execute(
            select(PrinterDevice.id, PrinterDevice.name).where(
                PrinterDevice.id.in_(query.with_only_columns(Batch.printer_id))
            )
        ).all()
    )
    cartridges = dict(
        session.execute(
            select(Cartridge.id, Cartridge.name).where(
                Cartridge.id.in_(query.with_only_columns(Batch.cartridge_id))
            )
        ).all()
    )
    requesters: dict[str, str] = {}
    approvers: dict[str, str] = {}
    snapshot: dict[str, Any] | None
    for snapshot in session.scalars(
        (
            items.with_only_columns(BatchItem.attribution)
            if items is not None
            else select(BatchItem.attribution)
        ).where(BatchItem.batch_id.in_(ids))
    ):
        if not snapshot:
            continue
        if requester := snapshot.get("requested_by"):
            requesters[requester["id"]] = requester["name"]
        for actor in authorizers(snapshot):
            approvers[actor["id"]] = actor["name"]
    return {
        kind: [
            {"id": identifier, "name": name}
            for identifier, name in sorted(
                values.items(), key=lambda item: (item[1].casefold(), item[0])
            )
        ]
        for kind, values in (
            ("printers", printers),
            ("cartridges", cartridges),
            ("requesters", requesters),
            ("authorizers", approvers),
        )
    }
