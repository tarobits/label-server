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

from app.assets.font_assets import FontStore
from app.assets.image_assets import ImageStore
from app.audit.print_audit import direct_attribution
from app.authn.access import AccessContext, Action, Resource, access_context
from app.authn.authorization import rendering_destination
from app.http import get, job_record
from app.models import JobSubmission, LabelCopy, LabelTemplate, PrintJob, TapeProfile
from app.printing.destinations import members
from app.printing.print_planning import geometry_plan, planning_backend
from app.render import RenderSpec, printable_vertical_bounds, render_document
from app.schemas import JobInput
from app.templates.template_schema import TemplateDocument


def rendering_spec(
    request: Request,
    document: TemplateDocument | dict[str, Any] | None = None,
    destination_id: str | None = None,
) -> RenderSpec:
    with request.app.state.factory() as session:
        authoring = request.url.path == "/api/preview" or request.url.path.startswith(
            ("/api/templates", "/api/logic/")
        )
        destination_id = rendering_destination(
            request, session, destination_id, allow_unassigned=authoring
        )
        if destination_id is None:
            from app.media import MediaProperties

            media = (
                document.media
                if isinstance(document, TemplateDocument)
                else MediaProperties.model_validate((document or {}).get("media", {}))
            )
            width = (
                document.width_mm
                if isinstance(document, TemplateDocument)
                else (document or {}).get("width_mm", 24)
            )
            return RenderSpec(
                stretch_canvas=True,
                media_family=media.media_family,
                media_kind=media.media_kind,
                fixed_label_sizes_mm=((width, media.label_length_mm),)
                if media.label_length_mm is not None
                else (),
            )
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
        align_printable_band=True,
        supported_widths_mm=capabilities.supported_widths_mm,
        dpi=dpi_y,
        dpi_x=dpi_x,
        margin_mm=capabilities.printable_margin_mm,
        media_kind=capabilities.media_kind.value,
        printable_widths_mm=capabilities.printable_widths_mm,
        media_family=capabilities.media_family,
        fixed_label_sizes_mm=capabilities.fixed_label_sizes_mm,
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
    if profile.available is False:
        raise HTTPException(409, "Tape profile is unavailable; choose another profile")
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
            if band:
                top, bottom = printable_vertical_bounds(profile.width_mm, spec)
            else:
                top = max(spec.margin_mm, min(2, profile.width_mm / 4))
                bottom = profile.width_mm - top
            document["elements"][0]["y"] = top
            document["elements"][0]["height"] = bottom - top
    if document["width_mm"] != profile.width_mm:
        raise HTTPException(422, "Template and tape widths do not match")
    try:
        parsed = TemplateDocument.model_validate(document)
        from app.media import require_matching_media

        require_matching_media(parsed.media, profile)
        output = render_document(parsed, body.data, spec, fonts=fonts, images=images)
        if (
            parsed.version == 2
            or parsed.auto_length
            or any(e.auto_width or e.distance_holder for e in parsed.elements)
        ):
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
            **({"billing": body.billing.model_dump()} if body.billing else {}),
            "name": template.name,
            "process_name": body.process_name or template.name,
            "profile_name": profile.name,
            "renderer": "svg",
            "revision": template.revision,
            "document": document,
            "render_spec": asdict(spec),
            "warnings": output.warnings,
            "template_padding_mm": output.template_padding_mm,
        },
        payload=body.model_copy(update={"data": output.resolved_inputs}).model_dump(mode="json")[
            "data"
        ]
        if output.resolved_inputs is not None
        else body.model_dump(mode="json")["data"],
        width_mm=profile.width_mm,
        length_mm=document["length_mm"],
        copies=body.copies,
        notify_on_completion=body.notify_on_completion,
    )


def input_fingerprint(values: dict[str, Any], namespace: str | None = None) -> str:
    # Keep retries of pre-multi-printer requests valid after upgrading.
    values = dict(values)
    for key in ("quote_id", "maximum_price", "billing"):
        if values.get(key) is None:
            values.pop(key, None)
    if values.get("image_mapping") == {}:
        values.pop("image_mapping")
    if values.get("notify_on_completion", True) is True:
        values.pop("notify_on_completion", None)
    if isinstance(values.get("rows"), list):
        values["rows"] = [
            {
                key: value
                for key, value in row.items()
                if (key != "notify_on_completion" or value is not True)
                and (key != "maximum_price" or value is not None)
            }
            for row in values["rows"]
        ]
    if values.get("process_name") is None:
        values.pop("process_name", None)
    if isinstance(values.get("input"), dict):
        values["input"] = dict(values["input"])
        for key in ("quote_id", "maximum_price", "billing"):
            if values["input"].get(key) is None:
                values["input"].pop(key, None)
        if values["input"].get("notify_on_completion", True) is True:
            values["input"].pop("notify_on_completion", None)
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
    access_context(request).require_printer(job.destination_id, "submit_directly")
    actor = access_context(request).actor
    job.owner_id = actor.id
    job.created_at = time.time()
    job.attribution = direct_attribution(actor, job.created_at)
    backend = planning_backend(request, session, job.destination_id)
    assert backend is not None
    spec = RenderSpec(**job.template_snapshot["render_spec"])
    job.template_snapshot = {
        **job.template_snapshot,
        "print_plan": geometry_plan(
            backend,
            job.width_mm,
            job.length_mm,
            spec.horizontal_dpi,
            spec.dpi,
            job.copies,
            job.template_snapshot.get("template_padding_mm", 0),
        ),
    }
    session.add(job)
    session.flush()
    from app.accounts.billing import register_job

    register_job(session, job, actor)
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
