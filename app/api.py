import copy
import hashlib
import json
import re
import time
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.access import AccessContext, Action, Resource, access_context
from app.font_assets import FontStore
from app.image_assets import ImageStore
from app.image_jobs import image_document
from app.models import (
    Base,
    Batch,
    BatchItem,
    Cartridge,
    FlushRequest,
    JobSubmission,
    LabelCopy,
    LabelTemplate,
    Notification,
    PrinterState,
    PrintJob,
    PrintRun,
    State,
    TapeProfile,
    TemplateRevision,
)
from app.notifications import schedule_reminders
from app.printer.mock import MockPrinterBackend
from app.queue import compatible_copies, require_idle, resolve_batch
from app.render import RenderSpec, render_document
from app.schemas import (
    ActiveTapeInput,
    AutomaticPrintingInput,
    CartridgeInput,
    CopySelectionInput,
    ImageJobInput,
    JobInput,
    MockPrinterInput,
    ProfileInput,
    RemainingInput,
    ReminderInput,
    ReviewInput,
)
from app.template_schema import PreviewInput, TemplateDocument, TemplateInput
from app.templates import template_record

T = TypeVar("T", bound=Base)
router = APIRouter(prefix="/api")


def db(request: Request) -> Iterator[Session]:
    # The single-process lock serializes API mutations with batch reservation.
    with request.app.state.worker.lock, request.app.state.factory.begin() as session:
        yield session
        if request.method != "GET":
            schedule_reminders(session, time.time())
    if request.method != "GET":
        request.app.state.wake.set()


def get(session: Session, model: type[T], identifier: str | int) -> T:
    value = session.get(model, identifier)
    if value is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return value


def record(value: Base) -> dict[str, Any]:
    return {column.key: getattr(value, column.key) for column in inspect(type(value)).columns}


def idle(session: Session) -> None:
    try:
        require_idle(session)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


def job_record(session: Session, job: PrintJob) -> dict[str, Any]:
    copies = list(
        session.scalars(
            select(LabelCopy).where(LabelCopy.job_id == job.id).order_by(LabelCopy.ordinal)
        )
    )
    states = {item.state for item in copies}
    status = next(
        (
            state.value
            for state in [State.NEEDS_REVIEW, State.PRINTING, State.QUEUED]
            if state in states
        ),
        None,
    )
    if status is None:
        status = next(iter(states)).value if len(states) == 1 else "mixed"
    return {**record(job), "status": status, "labels": [record(item) for item in copies]}


@router.get("/status")
def status(request: Request, session: Session = Depends(db, scope="function")) -> dict[str, Any]:
    state = get(session, PrinterState, 1)
    hardware = request.app.state.worker.latest_status
    return {
        **record(state),
        "backend": request.app.state.registry.definition("main").driver,
        "printer_name": request.app.state.registry.definition("main").name,
        "printer_error": hardware.error,
        "renderer": "svg",
        "connected": hardware.connected,
        "detected_width_mm": hardware.tape_width_mm,
        "needs_review": list(
            session.scalars(select(Batch.id).where(Batch.state == State.NEEDS_REVIEW))
        ),
        "notifications_enabled": bool(request.app.state.settings.ntfy_url),
        "printing": session.scalar(select(Batch.id).where(Batch.state == State.PRINTING).limit(1)),
        "pending_flush": session.scalar(
            select(FlushRequest.id)
            .where(
                FlushRequest.cartridge_id == state.active_cartridge_id,
                FlushRequest.completed.is_(False),
            )
            .limit(1)
        ),
        "queues": [
            {
                "profile_id": p.id,
                "queued_copies": len(compatible_copies(session, p)),
                "threshold": p.auto_print_threshold,
            }
            for p in session.scalars(select(TapeProfile))
        ],
    }


@router.get("/tape-profiles")
def list_profiles(session: Session = Depends(db, scope="function")) -> list[dict[str, Any]]:
    return [record(p) for p in session.scalars(select(TapeProfile).order_by(TapeProfile.name))]


@router.post("/tape-profiles", status_code=201)
def create_profile(
    body: ProfileInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    profile = TapeProfile(**body.model_dump())
    session.add(profile)
    session.flush()
    return record(profile)


@router.put("/tape-profiles/{identifier}")
def update_profile(
    identifier: str, body: ProfileInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    profile = get(session, TapeProfile, identifier)
    if profile.width_mm != body.width_mm:
        if session.scalar(
            select(PrintJob.id).where(PrintJob.profile_id == identifier).limit(1)
        ) or session.scalar(
            select(Cartridge.id).where(Cartridge.profile_id == identifier).limit(1)
        ):
            raise HTTPException(409, "Create a new profile to change the width of a used profile")
    for key, value in body.model_dump().items():
        setattr(profile, key, value)
    session.flush()
    return record(profile)


@router.delete("/tape-profiles/{identifier}")
def delete_profile(
    identifier: str, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    profile = get(session, TapeProfile, identifier)
    for query in [
        select(Cartridge.id).where(Cartridge.profile_id == identifier),
        select(PrintJob.id).where(PrintJob.profile_id == identifier),
        select(Notification.id).where(Notification.profile_id == identifier),
    ]:
        if session.scalar(query.limit(1)):
            raise HTTPException(409, "Profile has history or cartridges and cannot be deleted")
    session.delete(profile)
    return {"deleted": True}


@router.put("/tape-profiles/{identifier}/reminder")
def control_reminder(
    identifier: str, body: ReminderInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    profile = get(session, TapeProfile, identifier)
    if body.action == "snooze" and (body.until or 0) <= time.time():
        raise HTTPException(422, "Snooze must end in the future")
    profile.reminder_silenced = body.action == "silence"
    profile.reminder_snoozed_until = body.until if body.action == "snooze" else None
    if body.action == "resume":
        profile.reminder_last_at = None
    session.flush()
    return record(profile)


@router.get("/cartridges")
def list_cartridges(session: Session = Depends(db, scope="function")) -> list[dict[str, Any]]:
    return [record(c) for c in session.scalars(select(Cartridge))]


@router.post("/cartridges", status_code=201)
def create_cartridge(
    body: CartridgeInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    get(session, TapeProfile, body.profile_id)
    values = body.model_dump()
    values["remaining_mm"] = (
        body.nominal_length_mm if body.remaining_mm is None else body.remaining_mm
    )
    cartridge = Cartridge(**values)
    session.add(cartridge)
    session.flush()
    return record(cartridge)


@router.put("/cartridges/{identifier}/remaining")
def correct_remaining(
    identifier: str, body: RemainingInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    idle(session)
    cartridge = get(session, Cartridge, identifier)
    if body.remaining_mm > cartridge.nominal_length_mm:
        raise HTTPException(422, "Remaining length exceeds nominal length")
    cartridge.remaining_mm = body.remaining_mm
    cartridge.consumption_uncertain = False
    session.flush()
    return record(cartridge)


@router.put("/printer/active-tape")
def active_tape(
    body: ActiveTapeInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    idle(session)
    if body.cartridge_id:
        get(session, Cartridge, body.cartridge_id)
    state = get(session, PrinterState, 1)
    state.active_cartridge_id = body.cartridge_id
    state.blocker = None
    session.flush()
    return record(state)


def rendering_spec(
    request: Request, document: TemplateDocument | dict[str, Any] | None = None
) -> RenderSpec:
    capabilities = request.app.state.registry.definition("main").capabilities
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
        dpi=dpi_y,
        dpi_x=dpi_x,
        margin_mm=capabilities.printable_margin_mm,
        media_kind=capabilities.media_kind.value,
        printable_widths_mm=capabilities.printable_widths_mm,
    )


@router.get("/printers")
def printers(request: Request) -> list[dict[str, Any]]:
    return [asdict(item) for item in request.app.state.registry.definitions()]


@router.put("/printer/automatic-printing")
def automatic_printing(
    body: AutomaticPrintingInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    state = get(session, PrinterState, 1)
    state.automatic_printing_held = body.held
    session.flush()
    return record(state)


@router.get("/templates")
def templates(session: Session = Depends(db, scope="function")) -> list[dict[str, Any]]:
    return [
        template_record(t)
        for t in session.scalars(
            select(LabelTemplate)
            .where(LabelTemplate.archived.is_(False))
            .order_by(LabelTemplate.name)
        )
    ]


@router.get("/templates/{identifier}")
def template(identifier: str, session: Session = Depends(db, scope="function")) -> dict[str, Any]:
    return template_record(get(session, LabelTemplate, identifier))


def validate_layout(document: TemplateDocument, request: Request) -> None:
    try:
        render_document(
            document,
            {},
            rendering_spec(request, document),
            samples=True,
            fonts=request.app.state.fonts,
            images=request.app.state.images,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/templates", status_code=201)
def create_template(
    body: TemplateInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    validate_layout(body.document, request)
    value = LabelTemplate(
        name=body.name,
        document=body.document.model_dump(),
        owner_id=access_context(request).actor.id,
    )
    session.add(value)
    session.flush()
    session.add(
        TemplateRevision(
            template_id=value.id, revision=value.revision, name=value.name, document=value.document
        )
    )
    return template_record(value)


@router.put("/templates/{identifier}")
def update_template(
    identifier: str,
    body: TemplateInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    value = get(session, LabelTemplate, identifier)
    if value.archived or body.expected_revision != value.revision:
        raise HTTPException(409, "Template changed or was archived; reload before saving")
    validate_layout(body.document, request)
    value.name, value.document = body.name, body.document.model_dump()
    value.revision += 1
    session.add(
        TemplateRevision(
            template_id=value.id, revision=value.revision, name=value.name, document=value.document
        )
    )
    session.flush()
    return template_record(value)


@router.delete("/templates/{identifier}")
def archive_template(
    identifier: str, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    get(session, LabelTemplate, identifier).archived = True
    return {"archived": True}


@router.get("/templates/{identifier}/revisions")
def revisions(
    identifier: str, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    get(session, LabelTemplate, identifier)
    return [
        record(item)
        for item in session.scalars(
            select(TemplateRevision)
            .where(TemplateRevision.template_id == identifier)
            .order_by(TemplateRevision.revision.desc())
        )
    ]


@router.post("/preview")
def preview(
    body: PreviewInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    document = body.document or TemplateDocument.model_validate(
        get(session, LabelTemplate, body.template_id or "").document
    )
    try:
        output = render_document(
            document,
            body.data,
            rendering_spec(request, document),
            body.use_samples,
            fonts=request.app.state.fonts,
            images=request.app.state.images,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {
        "png": output.preview(body.foreground, body.background),
        "design_png": output.preview(body.foreground, body.background, smooth=True),
        "svg": output.svg,
        "pixel_width": output.image.width,
        "pixel_height": output.image.height,
        "warnings": output.warnings,
        "length_mm": output.document.length_mm,
        "width_mm": output.document.width_mm,
        "resolved_elements": [e.model_dump() for e in output.document.elements],
    }


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
    context.require(Action.READ, Resource("template", template.id, template.owner_id))
    document = copy.deepcopy(template.document)
    # Built-in text retains the original API's per-job tape and length options.
    if template.id == "text" and template.revision == 2:
        document["width_mm"] = profile.width_mm
        if body.length_mm is not None:
            document["length_mm"] = body.length_mm
        if document["elements"]:
            document["elements"][0]["width"] = document["length_mm"] - 4
            band = (spec.printable_widths_mm or {}).get(str(profile.width_mm))
            side = (profile.width_mm - band) / 2 if band else min(2, profile.width_mm / 4)
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
    return PrintJob(
        profile_id=profile.id,
        template_id=body.template,
        template_snapshot={
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


@router.post("/jobs", status_code=201)
def create_job(
    body: JobInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    existing = submitted_job(request, session, fingerprint)
    if existing is not None:
        return existing
    profile = get(session, TapeProfile, body.tape_profile)
    template = get(session, LabelTemplate, body.template)
    if template.archived:
        raise HTTPException(409, "Template is archived")
    job = build_job(
        body,
        profile,
        template,
        rendering_spec(request, template.document),
        request.app.state.fonts,
        request.app.state.images,
        context=access_context(request),
    )
    return save_submission(request, session, job, fingerprint)


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
    job.owner_id = access_context(request).actor.id
    job.destination_id = access_context(request).destination_id
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


def image_job_document(
    body: ImageJobInput, request: Request, session: Session
) -> tuple[TapeProfile, TemplateDocument]:
    profile = get(session, TapeProfile, body.tape_profile)
    try:
        asset = request.app.state.images.metadata(body.image_asset)
        access_context(request).require(
            Action.READ, Resource("image_asset", body.image_asset, asset["owner_id"])
        )
        document = image_document(
            body,
            profile.width_mm,
            rendering_spec(request, body.model_dump()),
            request.app.state.images,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return profile, document


@router.post("/image-jobs/preview")
def preview_image_job(
    body: ImageJobInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    profile, document = image_job_document(body, request, session)
    return preview(
        PreviewInput(
            document=document, foreground=profile.foreground, background=profile.background
        ),
        request,
        session,
    )


@router.post("/image-jobs", status_code=201)
def create_image_job(
    body: ImageJobInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    # Share the key namespace with template submissions, but never their fingerprints.
    fingerprint = hashlib.sha256(
        json.dumps({"image_job": body.model_dump()}, sort_keys=True).encode()
    ).hexdigest()
    existing = submitted_job(request, session, fingerprint)
    if existing is not None:
        return existing
    profile, document = image_job_document(body, request, session)
    # A frozen document needs no editable library template (nor a template per upload).
    template = LabelTemplate(
        id="image",
        name="Image label",
        revision=1,
        document=document.model_dump(),
        owner_id=access_context(request).actor.id,
    )
    job = build_job(
        JobInput(template="image", tape_profile=profile.id, copies=body.copies, data={}),
        profile,
        template,
        rendering_spec(request, document),
        request.app.state.fonts,
        request.app.state.images,
        context=access_context(request),
    )
    return save_submission(request, session, job, fingerprint)


@router.get("/jobs")
def list_jobs(
    limit: int = 100,
    offset: int = 0,
    copy_state: State | None = None,
    profile_id: str | None = None,
    session: Session = Depends(db, scope="function"),
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    query = select(PrintJob)
    if profile_id is not None:
        query = query.where(PrintJob.profile_id == profile_id)
    if copy_state is not None:
        query = query.where(
            select(LabelCopy.id)
            .where(
                LabelCopy.job_id == PrintJob.id,
                LabelCopy.state == copy_state,
            )
            .exists()
        )
    return [
        job_record(session, job)
        for job in session.scalars(
            query.order_by(PrintJob.created_at.desc(), PrintJob.id).offset(offset).limit(limit)
        )
    ]


@router.get("/queue/groups")
def queue_groups(
    limit: int = 25,
    offset: int = 0,
    copy_state: State | None = None,
    profile_id: str | None = None,
    session: Session = Depends(db, scope="function"),
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    query = select(PrintJob)
    if profile_id is not None:
        query = query.where(PrintJob.profile_id == profile_id)
    if copy_state is not None:
        query = query.where(
            select(LabelCopy.id)
            .where(LabelCopy.job_id == PrintJob.id, LabelCopy.state == copy_state)
            .exists()
        )
    key = func.coalesce(PrintJob.run_id, PrintJob.id)
    keys = session.execute(
        query.with_only_columns(key, func.max(PrintJob.created_at))
        .group_by(key)
        .order_by(func.max(PrintJob.created_at).desc(), key)
        .offset(offset)
        .limit(limit)
    ).all()
    result = []
    for identifier, _ in keys:
        jobs = list(
            session.scalars(
                query.where(key == identifier).order_by(PrintJob.run_position, PrintJob.id)
            )
        )
        run = session.get(PrintRun, jobs[0].run_id) if jobs[0].run_id else None
        result.append(
            {
                "id": identifier,
                "run_id": run.id if run else None,
                "name": run.name if run else None,
                "jobs": [job_record(session, job) for job in jobs],
            }
        )
    return result


@router.get("/jobs/{identifier}")
def job(identifier: str, session: Session = Depends(db, scope="function")) -> dict[str, Any]:
    return job_record(session, get(session, PrintJob, identifier))


@router.delete("/jobs/{identifier}")
def cancel_job(identifier: str, session: Session = Depends(db, scope="function")) -> dict[str, Any]:
    item = get(session, PrintJob, identifier)
    copies = list(session.scalars(select(LabelCopy).where(LabelCopy.job_id == identifier)))
    if any(c.state in (State.PRINTING, State.NEEDS_REVIEW) for c in copies):
        raise HTTPException(409, "Use batch review for printing or uncertain copies")
    for label in copies:
        if label.state == State.QUEUED:
            label.state = State.CANCELLED
    session.flush()
    return job_record(session, item)


@router.post("/queue/remove")
def remove_selected(
    body: CopySelectionInput, session: Session = Depends(db, scope="function")
) -> dict[str, int]:
    wanted = set(body.copy_ids)
    if len(wanted) != len(body.copy_ids):
        raise HTTPException(422, "Select each copy only once")
    copies = list(session.scalars(select(LabelCopy).where(LabelCopy.id.in_(wanted))))
    if len(copies) != len(wanted) or any(copy.state != State.QUEUED for copy in copies):
        raise HTTPException(409, "Selection changed; refresh the queue before removing items")
    job_ids = {copy.job_id for copy in copies}
    if session.scalar(
        select(LabelCopy.id)
        .where(
            LabelCopy.job_id.in_(job_ids), LabelCopy.state.in_([State.PRINTING, State.NEEDS_REVIEW])
        )
        .limit(1)
    ):
        raise HTTPException(409, "Use batch review for printing or uncertain copies")
    for label in copies:
        label.state = State.CANCELLED
    return {"removed_copies": len(copies)}


@router.post("/queue/print", status_code=202)
def flush_queue(
    body: CopySelectionInput | None = None, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    idle(session)
    state = get(session, PrinterState, 1)
    if not state.active_cartridge_id:
        raise HTTPException(409, "Select an installed cartridge first")
    cartridge = get(session, Cartridge, state.active_cartridge_id)
    profile = get(session, TapeProfile, cartridge.profile_id)
    pending = session.scalar(
        select(FlushRequest.id)
        .where(FlushRequest.cartridge_id == cartridge.id, FlushRequest.completed.is_(False))
        .limit(1)
    )
    if pending:
        raise HTTPException(409, "A manual flush is already pending for this cartridge")
    compatible = compatible_copies(session, profile)
    if body is not None:
        wanted = set(body.copy_ids)
        if len(wanted) != len(body.copy_ids):
            raise HTTPException(422, "Select each copy only once")
        if not wanted.issubset({copy.id for copy in compatible}):
            raise HTTPException(
                409,
                "Selection changed or includes copies incompatible with the installed tape; refresh the queue",
            )
        compatible = [copy for copy in compatible if copy.id in wanted]
        # Keep all unselected work queued even if it meets an automatic threshold.
        state.automatic_printing_held = True
    request = FlushRequest(cartridge_id=cartridge.id, copy_ids=[c.id for c in compatible])
    session.add(request)
    session.flush()
    return record(request)


@router.get("/batches")
def batches(session: Session = Depends(db, scope="function")) -> list[dict[str, Any]]:
    return [
        record(b)
        for b in session.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(100))
    ]


@router.get("/batches/{identifier}")
def batch_detail(
    identifier: str, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    batch = get(session, Batch, identifier)
    items = []
    for item in session.scalars(
        select(BatchItem).where(BatchItem.batch_id == identifier).order_by(BatchItem.position)
    ):
        label = get(session, LabelCopy, item.copy_id)
        job = get(session, PrintJob, label.job_id)
        items.append(
            {
                **record(item),
                "job_id": job.id,
                "copy_number": label.ordinal + 1,
                "text": job.payload.get("text", job.template_id),
            }
        )
    return {
        **record(batch),
        "items": items,
    }


@router.post("/batches/{identifier}/review")
def review(
    identifier: str, body: ReviewInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    batch = get(session, Batch, identifier)
    try:
        resolve_batch(
            session,
            batch,
            {key: State(value) for key, value in body.decisions.items()},
            body.consumed_mm,
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    session.flush()
    return record(batch)


@router.get("/notifications")
def notifications(session: Session = Depends(db, scope="function")) -> list[dict[str, Any]]:
    return [
        record(n)
        for n in session.scalars(
            select(Notification).order_by(Notification.created_at.desc()).limit(100)
        )
    ]


def mock_backend(request: Request) -> MockPrinterBackend:
    backend = request.app.state.worker.backend
    if not isinstance(backend, MockPrinterBackend):
        raise HTTPException(404, "Mock controls are unavailable for this printer")
    return backend


@router.get("/printer/mock")
def mock_settings(request: Request) -> dict[str, Any]:
    backend = mock_backend(request)
    return {
        "connected": backend.connected,
        "tape_width_mm": backend.width_mm,
        "fail_after": backend.fail_after,
    }


@router.put("/printer/mock")
def set_mock_settings(
    body: MockPrinterInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    backend = mock_backend(request)
    worker = request.app.state.worker
    # Nonblocking acquisition avoids reversing the worker's printer/database lock order.
    if not worker.printer_lock.acquire(blocking=False):
        raise HTTPException(409, "Printer is busy; try again after this batch")
    try:
        backend.connected = body.connected
        backend.width_mm = body.tape_width_mm
        backend.fail_after = body.fail_after
        worker.latest_status = backend.get_status()
    finally:
        worker.printer_lock.release()
    return mock_settings(request)
