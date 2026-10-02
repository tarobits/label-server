"""CSV authoring and durable frozen runs; no printer-specific protocol knowledge."""

import csv
import hashlib
import io
import json
import time
from dataclasses import replace
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.api import build_job, db, get, job_record, rendering_spec
from app.models import LabelCopy, LabelTemplate, PrintJob, PrintRun, TapeProfile
from app.printer.base import RenderedLabel
from app.render import RenderSpec, render_document, render_job
from app.schemas import Input, JobInput
from app.template_schema import TemplateDocument

router = APIRouter(prefix="/api")


class CsvInput(Input):
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    delimiter: Literal[",", ";", "\t"] = ","


class RunRow(Input):
    source_row: int = Field(ge=2, le=251)
    copies: int = Field(default=1, ge=1, le=1000)


class RunInput(CsvInput):
    request_key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    template: str
    expected_revision: int = Field(ge=1)
    tape_profile: str
    length_mm: float | None = Field(default=None, ge=10, le=300)
    mapping: dict[str, str] = Field(max_length=20)
    rows: list[RunRow] = Field(min_length=1, max_length=250)


def parse_csv(body: CsvInput) -> dict[str, Any]:
    if len(body.csv_text.encode("utf-8")) > 1_000_000:
        raise HTTPException(422, "CSV must not exceed 1 MB")
    try:
        reader = csv.reader(
            io.StringIO(body.csv_text.lstrip("\ufeff"), newline=""),
            delimiter=body.delimiter,
            strict=True,
        )
        header = next(reader)
        if not 1 <= len(header) <= 40 or any(not h.strip() or len(h) > 100 for h in header):
            raise ValueError("Use 1–40 named columns (at most 100 characters each)")
        if len(set(header)) != len(header):
            raise ValueError("CSV column names must be unique")
        rows = []
        for number, values in enumerate(reader, 2):
            if number > 251:
                raise ValueError("Import at most 250 data records at a time")
            if len(values) != len(header):
                raise ValueError(
                    f"Record {number}: expected {len(header)} columns, got {len(values)}"
                )
            if any(len(value) > 2000 for value in values):
                raise ValueError(f"Record {number}: a cell exceeds 2000 characters")
            rows.append({"source_row": number, "values": values})
        if not rows:
            raise ValueError("CSV contains no data records")
        return {"headers": header, "rows": rows}
    except (csv.Error, ValueError, StopIteration) as error:
        raise HTTPException(422, str(error) or "CSV is empty") from error


@router.post("/csv/parse")
def inspect_csv(body: CsvInput) -> dict[str, Any]:
    return parse_csv(body)


def run_record(run: PrintRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "name": run.name,
        "profile_id": run.profile_id,
        "owner_id": run.owner_id,
        "destination_id": run.destination_id,
        "created_at": run.created_at,
        "submitted_at": run.submitted_at,
        "rows": [
            {k: row[k] for k in ("source_row", "copies", "length_mm", "width_mm", "payload")}
            for row in run.manifest["rows"]
        ],
        "template_name": run.manifest["template_name"],
        "template_revision": run.manifest["template_revision"],
        "copies": sum(row["copies"] for row in run.manifest["rows"]),
        "estimated_mm": run.manifest["estimated_mm"],
        "label_length_mm": sum(row["copies"] * row["length_mm"] for row in run.manifest["rows"]),
    }


@router.post("/runs/prepare")
def prepare_run(
    body: RunInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    existing = session.scalar(select(PrintRun).where(PrintRun.request_key == body.request_key))
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, "Request key already used for different run inputs")
        return {"valid": True, "run": run_record(existing), "errors": []}
    parsed = parse_csv(body)
    profile = get(session, TapeProfile, body.tape_profile)
    template = get(session, LabelTemplate, body.template)
    if template.archived or template.revision != body.expected_revision:
        raise HTTPException(409, "Template changed or was archived; reload before preparing")
    fields = {f["name"] for f in template.document["fields"]}
    if set(body.mapping) - fields or set(body.mapping.values()) - set(parsed["headers"]):
        raise HTTPException(422, "Mapping contains an unknown field or CSV column")
    if len({row.source_row for row in body.rows}) != len(body.rows):
        raise HTTPException(422, "Select each source record once; use copies for duplicates")
    if sum(row.copies for row in body.rows) > 1000:
        raise HTTPException(422, "A run may contain at most 1000 copies")
    source = {row["source_row"]: row["values"] for row in parsed["rows"]}
    errors: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for selected in body.rows:
        if selected.source_row not in source:
            raise HTTPException(422, "Selected CSV record does not exist")
        data = {
            field: source[selected.source_row][parsed["headers"].index(column)]
            for field, column in body.mapping.items()
        }
        try:
            job = build_job(
                JobInput(
                    template=template.id,
                    tape_profile=profile.id,
                    data=data,
                    copies=selected.copies,
                    length_mm=body.length_mm,
                ),
                profile,
                template,
                rendering_spec(request),
                request.app.state.fonts,
                request.app.state.images,
                access_context(request),
            )
            entries.append(
                {
                    "source_row": selected.source_row,
                    "copies": job.copies,
                    "length_mm": job.length_mm,
                    "width_mm": job.width_mm,
                    "template_id": job.template_id,
                    "template_snapshot": job.template_snapshot,
                    "payload": job.payload,
                }
            )
        except HTTPException as error:
            errors.append({"source_row": selected.source_row, "message": str(error.detail)})
    if errors:
        return {"valid": False, "errors": errors, "run": None}
    labels: list[RenderedLabel] = []
    for index, entry in enumerate(entries):
        label = render_job(
            PrintJob(**entry),
            LabelCopy(id=str(index)),
            request.app.state.fonts,
            request.app.state.images,
        )
        labels.extend(replace(label, copy_id=f"{index}:{copy}") for copy in range(entry["copies"]))
    estimate = request.app.state.worker.backend.estimate_consumption(labels)
    run = PrintRun(
        owner_id=access_context(request).actor.id,
        destination_id=access_context(request).destination_id,
        name=body.name,
        request_key=body.request_key,
        request_hash=fingerprint,
        profile_id=profile.id,
        manifest={
            "rows": entries,
            "estimated_mm": estimate,
            "template_name": template.name,
            "template_revision": template.revision,
            "foreground": profile.foreground,
            "background": profile.background,
        },
    )
    session.add(run)
    session.flush()
    return {"valid": True, "errors": [], "run": run_record(run)}


@router.get("/runs")
def list_runs(session: Session = Depends(db, scope="function")) -> list[dict[str, Any]]:
    return [
        run_record(run)
        for run in session.scalars(select(PrintRun).order_by(PrintRun.created_at.desc()).limit(100))
    ]


@router.get("/runs/{identifier}")
def show_run(identifier: str, session: Session = Depends(db, scope="function")) -> dict[str, Any]:
    return run_record(get(session, PrintRun, identifier))


@router.get("/runs/{identifier}/rows/{position}/preview")
def preview_run_row(
    identifier: str,
    position: int,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    run = get(session, PrintRun, identifier)
    rows = run.manifest["rows"]
    if not 0 <= position < len(rows):
        raise HTTPException(404, "Run row not found")
    row = rows[position]
    snapshot = row["template_snapshot"]
    output = render_document(
        TemplateDocument.model_validate(snapshot["document"]),
        row["payload"],
        RenderSpec(**snapshot["render_spec"]),
        fonts=request.app.state.fonts,
        images=request.app.state.images,
    )
    return {
        "png": output.preview(run.manifest["foreground"], run.manifest["background"]),
        "design_png": output.preview(
            run.manifest["foreground"], run.manifest["background"], smooth=True
        ),
        "warnings": output.warnings,
        "length_mm": row["length_mm"],
        "width_mm": row["width_mm"],
    }


@router.post("/runs/{identifier}/submit")
def submit_run(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    run = get(session, PrintRun, identifier)
    access_context(request).require(
        Action.SUBMIT, Resource("run", run.id, run.owner_id, run.destination_id)
    )
    if run.submitted_at is None:
        profile = get(session, TapeProfile, run.profile_id)
        if any(row["width_mm"] != profile.width_mm for row in run.manifest["rows"]):
            raise HTTPException(409, "Tape width changed; prepare a new run")
        stamp = time.time()
        for position, row in enumerate(run.manifest["rows"]):
            job = PrintJob(
                **row,
                profile_id=run.profile_id,
                owner_id=run.owner_id,
                destination_id=run.destination_id,
                run_id=run.id,
                run_position=position,
                created_at=stamp,
            )
            session.add(job)
            session.flush()
            session.add_all([LabelCopy(job_id=job.id, ordinal=i) for i in range(job.copies)])
        run.submitted_at = stamp
        session.flush()
    return {
        "run": run_record(run),
        "jobs": [
            job_record(session, job)
            for job in session.scalars(
                select(PrintJob).where(PrintJob.run_id == run.id).order_by(PrintJob.run_position)
            )
        ],
    }


@router.delete("/runs/{identifier}")
def delete_draft(
    identifier: str, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    run = get(session, PrintRun, identifier)
    if run.submitted_at is not None:
        raise HTTPException(409, "Submitted runs cannot be deleted; cancel queued copies instead")
    session.delete(run)
    return {"deleted": True}
