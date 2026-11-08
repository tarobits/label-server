"""History filtering uses frozen attribution rather than live user permissions."""

from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.models import Batch, BatchItem, Cartridge, PrinterDevice


def filter_batches(
    query: Select[Batch],
    printer: str | None,
    cartridge: str | None,
    requester: str | None,
    authorizer: str | None,
) -> Select[Batch]:
    if printer:
        query = query.where(Batch.printer_id == printer)
    if cartridge:
        query = query.where(Batch.cartridge_id == cartridge)
    attribution = BatchItem.attribution
    if requester:
        query = query.where(
            Batch.id.in_(
                select(BatchItem.batch_id).where(
                    attribution["requested_by"]["id"].as_string() == requester
                )
            )
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
        query = query.where(Batch.id.in_(select(BatchItem.batch_id).where(or_(*conditions))))
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


def filter_options(session: Session, query: Select[Batch]) -> dict[str, Any]:
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
        select(BatchItem.attribution).where(BatchItem.batch_id.in_(ids))
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
