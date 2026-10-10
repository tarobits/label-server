"""Immutable human attribution for submissions and individual physical attempts."""

import copy
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import Actor
from app.job_access_models import JobAccessHold
from app.models import Batch, BatchItem, PrintJob, User


def actor_snapshot(actor: Actor) -> dict[str, str] | None:
    # Explicit test/local-owner injection supplies no authenticated person.
    return {"id": actor.id, "name": actor.username} if actor.username else None


def unknown_attribution() -> dict[str, Any]:
    return {
        "requested_by": None,
        "requested_at": None,
        "authorization": {"kind": "unknown", "actor": None, "at": None, "request_id": None},
        "release": None,
    }


def direct_attribution(actor: Actor, at: float) -> dict[str, Any]:
    person = actor_snapshot(actor)
    return {
        "requested_by": copy.deepcopy(person),
        "requested_at": at,
        "authorization": {"kind": "direct", "actor": person, "at": at, "request_id": None},
        "release": None,
    }


def delegated_attribution(
    requester: User | None, submitter: Actor, at: float, *, override: bool = False
) -> dict[str, Any]:
    """Keep a draft's owner separate from the administrator submitting it."""
    result = direct_attribution(submitter, at)
    result["requested_by"] = {"id": requester.id, "name": requester.username} if requester else None
    result["submitted_by"] = actor_snapshot(submitter)
    if override:
        result["authorization"]["kind"] = "override"
    return result


def approval_attribution(
    requested_by: dict[str, str] | None,
    requested_at: float,
    approver: Actor,
    approved_at: float,
    request_id: str,
) -> dict[str, Any]:
    return {
        "requested_by": copy.deepcopy(requested_by),
        "requested_at": requested_at,
        "authorization": {
            "kind": "approval",
            "actor": actor_snapshot(approver),
            "at": approved_at,
            "request_id": request_id,
        },
        "release": None,
    }


def job_attribution(session: Session, job: PrintJob) -> dict[str, Any]:
    """Current job intent; copy this projection into an attempt before any I/O."""
    result = copy.deepcopy(job.attribution) if job.attribution else unknown_attribution()
    hold = session.get(JobAccessHold, job.id)
    result["release"] = (
        {"actor": copy.deepcopy(hold.resolved_by_snapshot), "at": hold.resolved_at}
        if hold and hold.status == "released" and hold.resolved_at is not None
        else None
    )
    return result


def batch_audit(session: Session, batch: Batch) -> dict[str, Any]:
    """History depends exclusively on saved attempts, never current identity data."""
    summary: dict[str, dict[str, Any]] = {}
    snapshot: dict[str, Any] | None
    for snapshot in session.scalars(
        select(BatchItem.attribution)
        .where(BatchItem.batch_id == batch.id)
        .order_by(BatchItem.position)
    ):
        attribution: dict[str, Any] = copy.deepcopy(snapshot) if snapshot else unknown_attribution()
        key = json.dumps(attribution, sort_keys=True)
        if key not in summary:
            summary[key] = {"attribution": attribution, "copies": 0}
        summary[key]["copies"] += 1
    return {
        "trigger": copy.deepcopy(batch.trigger)
        if batch.trigger
        else {
            "kind": "unknown",
            "actor": None,
            "at": None,
            "flush_request_id": None,
        },
        "attribution_summary": list(summary.values()),
    }
