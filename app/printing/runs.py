"""CSV authoring and durable frozen runs; no printer-specific protocol knowledge."""

import csv
import io
import time
from dataclasses import asdict, replace
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cost_estimates import estimate_cost
from app.audit.print_audit import delegated_attribution, direct_attribution
from app.authn.access import Action, Resource, access_context
from app.authn.authorization import rendering_destination, require_record, visible_runs
from app.http import db, get, job_record
from app.models import LabelCopy, LabelTemplate, PrintJob, PrintRun, TapeProfile, User
from app.printer.base import LabelGeometry, RenderedLabel
from app.printing.destinations import members
from app.printing.job_access import principal_access_reason
from app.printing.preparation import rendering
from app.printing.submissions import build_job, input_fingerprint, rendering_spec
from app.render import RenderSpec, render_document, render_job
from app.schemas import BillingSelection, Input, JobInput, MaximumPrice, ProcessName
from app.templates.logic_schema import ImageValue
from app.templates.template_logic import csv_values, logic_fields
from app.templates.template_schema import TemplateDocument
from app.transaction_routes import TransactionRouter

router = TransactionRouter(prefix="/api")


class CsvInput(Input):
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    delimiter: Literal[",", ";", "\t"] = ","


class RunRow(Input):
    source_row: int = Field(ge=2, le=251)
    copies: int = Field(default=1, ge=1, le=1000)
    notify_on_completion: bool = True
    maximum_price: MaximumPrice | None = None


class RunInput(CsvInput):
    billing: BillingSelection | None = None
    process_name: ProcessName | None = None
    destination_id: str | None = None
    request_key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    template: str
    expected_revision: int = Field(ge=1)
    tape_profile: str
    length_mm: float | None = Field(default=None, ge=10, le=300)
    mapping: dict[str, str] = Field(max_length=20)
    image_mapping: dict[
        str,
        Annotated[dict[Annotated[str, Field(max_length=2000)], ImageValue], Field(max_length=250)],
    ] = Field(default_factory=dict, max_length=20)
    rows: list[RunRow] = Field(min_length=1, max_length=250)


class SubmitRunInput(Input):
    authorization_override: bool = False


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
        "process_name": run.manifest.get("process_name", run.manifest["template_name"]),
        "profile_id": run.profile_id,
        "owner_id": run.owner_id,
        "destination_id": run.destination_id,
        "assigned_printer_id": run.assigned_printer_id,
        "created_at": run.created_at,
        "submitted_at": run.submitted_at,
        "rows": [
            {
                **{k: row[k] for k in ("source_row", "copies", "length_mm", "width_mm", "payload")},
                "notify_on_completion": row.get("notify_on_completion", True),
                "cost_estimate": row["template_snapshot"].get("cost_estimate"),
                "maximum_price": row["template_snapshot"].get("pricing", {}).get("maximum"),
            }
            for row in run.manifest["rows"]
        ],
        "template_name": run.manifest["template_name"],
        "template_revision": run.manifest["template_revision"],
        "copies": sum(row["copies"] for row in run.manifest["rows"]),
        "estimated_mm": run.manifest["estimated_mm"],
        "print_plan": run.manifest.get("print_plan"),
        "warnings": list(
            dict.fromkeys(
                warning
                for row in run.manifest["rows"]
                for warning in row["template_snapshot"].get("warnings", [])
            )
        ),
        "label_length_mm": sum(row["copies"] * row["length_mm"] for row in run.manifest["rows"]),
    }


def quoted_run(run: PrintRun, request: Request, session: Session) -> dict[str, Any]:
    cost = None
    if run.submitted_at is None:
        labels: list[LabelGeometry] = []
        for index, row in enumerate(run.manifest["rows"]):
            snapshot = row["template_snapshot"]
            spec = snapshot.get("render_spec", {})
            labels.extend(
                LabelGeometry(
                    f"{index}:{copy}",
                    row["width_mm"],
                    row["length_mm"],
                    spec.get("dpi_x") or spec.get("dpi", 180),
                    spec.get("dpi", 180),
                    snapshot.get("template_padding_mm", 0),
                )
                for copy in range(row["copies"])
            )
        cost = estimate_cost(request, session, run.destination_id, run.profile_id, labels)
    return {**run_record(run), "cost_estimate": cost}


@router.post("/runs/prepare")
def prepare_run(
    body: RunInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    owner = access_context(request).actor.id
    # Keep legacy local-owner receipts, namespace new account keys without changing
    # clients' retry keys or exposing collisions between unrelated users.
    from app.authn.identity import LOCAL_OWNER_ID

    stored_key = (
        body.request_key
        if owner == LOCAL_OWNER_ID
        else input_fingerprint({"owner": owner, "key": body.request_key})
    )
    existing = session.scalar(
        select(PrintRun).where(PrintRun.request_key == stored_key, PrintRun.owner_id == owner)
    )
    body.destination_id = (
        (body.destination_id or existing.destination_id)
        if existing
        else rendering_destination(request, session, body.destination_id)
    )
    assert body.destination_id is not None
    access_context(request).require_printer(body.destination_id, "view")
    fingerprint = input_fingerprint(body.model_dump())
    if existing:
        require_record(request, existing)
        if existing.request_hash != fingerprint:
            raise HTTPException(409, "Request key already used for different run inputs")
        return {"valid": True, "run": quoted_run(existing, request, session), "errors": []}
    parsed = parse_csv(body)
    profile = get(session, TapeProfile, body.tape_profile)
    if not profile.available:
        raise HTTPException(409, "Tape profile is unavailable; choose another profile")
    template = get(session, LabelTemplate, body.template)
    if template.archived or template.revision != body.expected_revision:
        raise HTTPException(409, "Template changed or was archived; reload before preparing")
    fields = {f["name"] for f in template.document["fields"]}
    document = TemplateDocument.model_validate(template.document)
    image_fields = (
        {field.name for field in logic_fields(document) if field.type == "image"}
        if document.version == 2
        else set()
    )
    if set(body.image_mapping) - image_fields:
        raise HTTPException(422, "Image mappings must refer to image variables")
    if set(body.mapping) - fields or set(body.mapping.values()) - set(parsed["headers"]):
        raise HTTPException(422, "Mapping contains an unknown field or CSV column")
    if len({row.source_row for row in body.rows}) != len(body.rows):
        raise HTTPException(422, "Select each source record once; use copies for duplicates")
    if sum(row.copies for row in body.rows) > 1000:
        raise HTTPException(422, "A run may contain at most 1000 copies")
    source = {row["source_row"]: row["values"] for row in parsed["rows"]}
    errors: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    spec = rendering_spec(request, template.document, body.destination_id)
    configured_member = next(
        (
            identifier
            for identifier in members(session, body.destination_id)
            if identifier in request.app.state.fleet.workers
        ),
        None,
    )
    if configured_member is None:
        raise HTTPException(409, "No configured printer is available at this destination")
    backend = request.app.state.registry.backend(configured_member)
    with rendering(
        request,
        session,
        body.model_dump(mode="json")["image_mapping"],
        destination_id=body.destination_id,
    ):
        for selected in body.rows:
            if selected.source_row not in source:
                raise HTTPException(422, "Selected CSV record does not exist")
            data = {
                field: source[selected.source_row][parsed["headers"].index(column)]
                for field, column in body.mapping.items()
            }
            try:
                typed_data = csv_values(document, data, body.image_mapping)
                job = build_job(
                    JobInput(
                        process_name=body.process_name,
                        billing=body.billing,
                        template=template.id,
                        destination_id=body.destination_id,
                        tape_profile=profile.id,
                        data=typed_data,
                        copies=selected.copies,
                        notify_on_completion=selected.notify_on_completion,
                        length_mm=body.length_mm,
                    ),
                    profile,
                    template,
                    spec,
                    request.app.state.fonts,
                    request.app.state.images,
                    context=access_context(request),
                )
                from app.accounts.pricing import accept_quote, job_geometry

                estimate = estimate_cost(
                    request, session, body.destination_id, profile.id, job_geometry(job)
                )
                accept_quote(
                    request,
                    session,
                    job,
                    estimate.get("quote_id"),
                    selected.maximum_price.model_dump() if selected.maximum_price else None,
                )
                job.template_snapshot = {**job.template_snapshot, "cost_estimate": estimate}
                entries.append(
                    {
                        "source_row": selected.source_row,
                        "copies": job.copies,
                        "notify_on_completion": job.notify_on_completion,
                        "length_mm": job.length_mm,
                        "width_mm": job.width_mm,
                        "template_id": job.template_id,
                        "template_snapshot": job.template_snapshot,
                        "payload": job.payload,
                    }
                )
            except HTTPException as error:
                errors.append({"source_row": selected.source_row, "message": str(error.detail)})
            except ValueError as error:
                errors.append({"source_row": selected.source_row, "message": str(error)})
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
            labels.extend(
                replace(label, copy_id=f"{index}:{copy}") for copy in range(entry["copies"])
            )

        estimate = backend.estimate_consumption(labels)
    existing = session.scalar(
        select(PrintRun).where(PrintRun.request_key == stored_key, PrintRun.owner_id == owner)
    )
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, "Request key already used for different run inputs")
        return {"valid": True, "run": quoted_run(existing, request, session), "errors": []}
    run = PrintRun(
        owner_id=access_context(request).actor.id,
        destination_id=body.destination_id,
        name=body.name,
        request_key=stored_key,
        request_hash=fingerprint,
        profile_id=profile.id,
        manifest={
            "process_name": body.process_name or template.name,
            "rows": entries,
            "estimated_mm": estimate,
            "print_plan": asdict(backend.plan_batch(labels)),
            "template_name": template.name,
            "template_revision": template.revision,
            "foreground": profile.foreground,
            "background": profile.background,
        },
    )
    session.add(run)
    session.flush()
    return {"valid": True, "errors": [], "run": quoted_run(run, request, session)}


@router.get("/runs")
def list_runs(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    query = visible_runs(request, session, select(PrintRun).order_by(PrintRun.created_at.desc()))
    return [run_record(run) for run in session.scalars(query.limit(100))]


@router.get("/runs/{identifier}")
def show_run(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return quoted_run(get(session, PrintRun, identifier), request, session)


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
        allow_missing_assets=True,
    )
    return {
        "png": output.preview(run.manifest["foreground"], run.manifest["background"]),
        "design_png": output.preview(
            run.manifest["foreground"], run.manifest["background"], smooth=True
        ),
        "warnings": list(dict.fromkeys([*snapshot.get("warnings", []), *output.warnings])),
        "length_mm": row["length_mm"],
        "width_mm": row["width_mm"],
    }


@router.post("/runs/{identifier}/submit")
def submit_run(
    identifier: str,
    request: Request,
    body: SubmitRunInput | None = None,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    run = get(session, PrintRun, identifier)
    context = access_context(request)
    override_requested = body is not None and body.authorization_override
    if override_requested and not context.actor.is_admin:
        raise HTTPException(403, "Only administrators may override the author's print access")
    context.require_printer(run.destination_id, "submit_directly")
    if run.owner_id != context.actor.id:
        context.require_printer(run.destination_id, "manage_queue")
    access_context(request).require(
        Action.SUBMIT, Resource("run", run.id, run.owner_id, run.destination_id)
    )
    from app.printing.request_models import PrintRequest

    if session.scalar(select(PrintRequest.id).where(PrintRequest.run_id == run.id)):
        raise HTTPException(409, "This run belongs to an approval request")
    members(session, run.destination_id)
    if run.submitted_at is None:
        profile = get(session, TapeProfile, run.profile_id)
        if any(row["width_mm"] != profile.width_mm for row in run.manifest["rows"]):
            raise HTTPException(409, "Tape width changed; prepare a new run")
        author = session.get(User, run.owner_id)
        delegated = run.owner_id != context.actor.id
        discrepancy = (
            principal_access_reason(
                session, run.owner_id, run.destination_id, "print", principal="original author"
            )
            if delegated
            else None
        )
        if discrepancy and not override_requested:
            name = author.username if author else run.owner_id
            raise HTTPException(
                409,
                {
                    "code": "owner_access_discrepancy",
                    "message": (
                        f"{name}: {discrepancy}. Confirm an administrator override to print "
                        "using your authorization while retaining the original author's ownership."
                    ),
                    "override_allowed": context.actor.is_admin,
                },
            )
        override = discrepancy is not None and override_requested
        stamp = time.time()
        attribution = (
            delegated_attribution(author, context.actor, stamp, override=override)
            if delegated
            else direct_attribution(context.actor, stamp)
        )
        for position, row in enumerate(run.manifest["rows"]):
            job = PrintJob(
                **row,
                profile_id=run.profile_id,
                owner_id=run.owner_id,
                destination_id=run.destination_id,
                run_id=run.id,
                run_position=position,
                created_at=stamp,
                authorization_basis="override" if override else "print",
                attribution=attribution,
            )
            session.add(job)
            session.flush()
            from app.accounts.billing import register_job
            from app.authn.auth import actor_for_user

            if job.template_snapshot.get("billing"):
                owner = session.get(User, job.owner_id)
                if owner is None:
                    raise HTTPException(409, "The original requester is unavailable")
                register_job(session, job, actor_for_user(session, owner))
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
    from app.printing.request_models import PrintRequest

    if session.scalar(
        select(PrintRequest.id).where(
            PrintRequest.run_id == run.id, PrintRequest.status == "pending"
        )
    ):
        raise HTTPException(409, "This draft has a pending approval request")
    session.delete(run)
    return {"deleted": True}
