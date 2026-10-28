"""Generic output planning; physical limits are supplied exclusively by adapters."""

from dataclasses import asdict
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.authorization import rendering_destination
from app.destinations import members
from app.printer.base import LabelGeometry, PrinterBackend
from app.printer.registry import PrinterRegistry


def planning_backend(
    request: Request,
    session: Session,
    destination_id: str | None,
    *,
    allow_unassigned: bool = False,
) -> PrinterBackend | None:
    destination_id = rendering_destination(
        request, session, destination_id, allow_unassigned=allow_unassigned
    )
    if destination_id is None:
        return None
    registry: PrinterRegistry = request.app.state.registry
    for identifier in members(session, destination_id):
        if identifier in request.app.state.fleet.workers:
            return registry.backend(identifier)
    raise HTTPException(409, "No configured printer is available at this destination")


def geometry_plan(
    backend: PrinterBackend,
    width_mm: float,
    length_mm: float,
    dpi_x: int,
    dpi_y: int,
    copies: int = 1,
    template_padding_mm: float = 0,
) -> dict[str, Any]:
    return asdict(
        backend.plan_batch(
            [
                LabelGeometry(str(index), width_mm, length_mm, dpi_x, dpi_y, template_padding_mm)
                for index in range(copies)
            ]
        )
    )


def queued_plan(
    request: Request, session: Session, jobs: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Estimate visible queued copies as one batch, with one leader, without rasterizing."""
    labels = queued_geometry(jobs)
    if not labels:
        return None
    # Job visibility already authorizes these label dimensions. A held job may
    # outlive destination access; do not turn a planning hint into a read boundary.
    try:
        identifiers = members(session, jobs[0]["destination_id"])
    except HTTPException:
        return None
    registry: PrinterRegistry = request.app.state.registry
    for identifier in identifiers:
        if identifier in request.app.state.fleet.workers:
            return asdict(registry.backend(identifier).plan_batch(labels))
    return None


def queued_geometry(jobs: list[dict[str, Any]]) -> list[LabelGeometry]:
    labels = []
    for job in jobs:
        snapshot = job["template_snapshot"]
        spec = snapshot.get("render_spec", {})
        for label in job["labels"]:
            if label["state"] != "queued":
                continue
            labels.append(
                LabelGeometry(
                    label["id"],
                    job["width_mm"],
                    job["length_mm"],
                    spec.get("dpi_x") or spec.get("dpi", 180),
                    spec.get("dpi", 180),
                    snapshot.get("template_padding_mm", 0),
                )
            )
    return labels
