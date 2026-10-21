"""Shared job construction, frozen rendering settings and idempotency receipts."""

import copy
import hashlib
import json
import re
import time
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.access import AccessContext, Action, Resource, access_context
from app.authorization import rendering_destination
from app.destinations import members
from app.font_assets import FontStore
from app.http import get, job_record
from app.image_assets import ImageStore
from app.models import JobSubmission, LabelCopy, LabelTemplate, PrintJob, TapeProfile
from app.print_audit import direct_attribution
from app.render import RenderSpec, render_document
from app.schemas import JobInput
from app.template_schema import TemplateDocument


def rendering_spec(
    request: Request,
    document: TemplateDocument | dict[str, Any] | None = None,
    destination_id: str | None = None,
) -> RenderSpec:
    with request.app.state.factory() as session:
        authoring = request.url.path == "/api/preview" or request.url.path.startswith(
            "/api/templates"
        )
        destination_id = rendering_destination(
            request, session, destination_id, allow_unassigned=authoring
        )
        if destination_id is None:
            return RenderSpec(stretch_canvas=True)
        access_context(request).require(
            Action.READ, Resource("destination", destination_id, destination_id=destination_id)
        )
        identifiers = members(session, destination_id)
    configured_members = [
        identifier for identifier in identifiers if identifier in request.app.state.fleet.workers
    ]
    if not configured_members:
        raise HTTPException(409, "No configured printer is available at this destination")
    capabilities = request.app.state.registry.definition(configured_members[0]).capabilities
    mode = (
        document.print_resolution
        if isinstance(document, TemplateDocument)
        else (document or {}).get("print_resolution", "printer")
    )
    dpi_x, dpi_y = capabilities.dpi_x, capabilities.dpi_y
    if mode != "printer":
        supported = capabilities.resolution_modes or {}
        if mode not in supported:
            raise HTTPException(
                422, "The selected printer does not support this template resolution"
            )
        dpi_x, dpi_y = supported[mode]
    return RenderSpec(
        stretch_canvas=True,
        supported_widths_mm=capabilities.supported_widths_mm,
        dpi=dpi_y,
        dpi_x=dpi_x,
        margin_mm=capabilities.printable_margin_mm,
        media_kind=capabilities.media_kind.value,
        printable_widths_mm=capabilities.printable_widths_mm,
    )


def build_job(
    body: JobInput,
    profile: TapeProfile,
    template: LabelTemplate,
    spec: RenderSpec,
    fonts: FontStore | None = None,
    images: ImageStore | None = None,
    *,
    context: AccessContext,
) -> PrintJob:
    context.require(
        Action.READ,
        Resource(
            "template",
            template.id,
            template.owner_id,
            scope=template.scope,
            group_id=template.group_id,
        ),
    )
    document = copy.deepcopy(template.document)
    # Built-in text retains the original API's per-job tape and length options.
    if template.id == "text" and template.revision == 2:
        document["width_mm"] = profile.width_mm
        if body.length_mm is not None:
            document["length_mm"] = body.length_mm
        if document["elements"]:
            document["elements"][0]["width"] = document["length_mm"] - 4
            band = (spec.printable_widths_mm or {}).get(f"{profile.width_mm:g}")
            side = (
                (profile.width_mm - band) / 2
                if band
                else max(spec.margin_mm, min(2, profile.width_mm / 4))
            )
            document["elements"][0]["y"] = side
            document["elements"][0]["height"] = profile.width_mm - 2 * side
    if document["width_mm"] != profile.width_mm:
        raise HTTPException(422, "Template and tape widths do not match")
    try:
        parsed = TemplateDocument.model_validate(document)
        output = render_document(parsed, body.data, spec, fonts=fonts, images=images)
        if parsed.auto_length or any(e.auto_width or e.distance_holder for e in parsed.elements):
            document = output.document.model_dump()
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    context.require(
        Action.SUBMIT,
        Resource("destination", body.destination_id, destination_id=body.destination_id),
    )
    return PrintJob(
        destination_id=body.destination_id,
        profile_id=profile.id,
        template_id=body.template,
        template_snapshot={
            "name": template.name,
            "process_name": body.process_name or template.name,
            "profile_name": profile.name,
            "renderer": "svg",
            "revision": template.revision,
            "document": document,
            "render_spec": asdict(spec),
        },
        payload=body.data,
        width_mm=profile.width_mm,
        length_mm=document["length_mm"],
        copies=body.copies,
    )


def input_fingerprint(values: dict[str, Any], namespace: str | None = None) -> str:
    # Keep retries of pre-multi-printer requests valid after upgrading.
    values = dict(values)
    if values.get("process_name") is None:
        values.pop("process_name", None)
    if isinstance(values.get("input"), dict):
        values["input"] = dict(values["input"])
        if values["input"].get("process_name") is None:
            values["input"].pop("process_name", None)
    if values.get("destination_id") == "main":
        values.pop("destination_id")
    payload = {namespace: values} if namespace else values
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def submitted_job(request: Request, session: Session, fingerprint: str) -> dict[str, Any] | None:
    key = request.headers.get("Idempotency-Key")
    owner = access_context(request).actor.id
    if key is not None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise HTTPException(
                422,
                "Idempotency-Key must be 1–128 letters, digits, dots, colons, underscores or hyphens",
            )
        receipt = session.get(JobSubmission, (owner, key))
        if receipt:
            if receipt.request_hash != fingerprint:
                raise HTTPException(409, "Idempotency-Key already used with different inputs")
            return job_record(session, get(session, PrintJob, receipt.job_id))
    return None


def save_submission(
    request: Request, session: Session, job: PrintJob, fingerprint: str
) -> dict[str, Any]:
    access_context(request).require_destination(job.destination_id, "print")
    actor = access_context(request).actor
    job.owner_id = actor.id
    job.created_at = time.time()
    job.attribution = direct_attribution(actor, job.created_at)
    session.add(job)
    session.flush()
    key = request.headers.get("Idempotency-Key")
    if key is not None:
        session.add(
            JobSubmission(
                owner_id=job.owner_id, request_key=key, request_hash=fingerprint, job_id=job.id
            )
        )
    session.add_all([LabelCopy(job_id=job.id, ordinal=i) for i in range(job.copies)])
    session.flush()
    return job_record(session, job)


def submission_destination(request: Request, session: Session, destination_id: str | None) -> str:
    key = request.headers.get("Idempotency-Key")
    if key:
        receipt = session.get(JobSubmission, (access_context(request).actor.id, key))
        if receipt:
            return destination_id or get(session, PrintJob, receipt.job_id).destination_id
    resolved = rendering_destination(request, session, destination_id)
    assert resolved is not None
    return resolved
