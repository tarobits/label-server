import io
import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.asset_access import require_document_assets
from app.authorization import (
    require_record,
    template_access,
    template_scope,
    visible_destinations,
    visible_jobs,
)
from app.deletion import document_notices, retain
from app.destinations import printer_state, resolve_destination
from app.http import db, get, idle, job_information, job_record, job_template_name, record
from app.image_jobs import image_document
from app.models import (
    Batch,
    BatchItem,
    Cartridge,
    FlushRequest,
    LabelCopy,
    LabelTemplate,
    Notification,
    NotificationDelivery,
    PrinterState,
    PrintJob,
    PrintRun,
    State,
    TapeProfile,
    TemplateRevision,
)
from app.notification_routing import notifications_enabled
from app.notifications import clear_empty_cartridge_alert
from app.preparation import rendering
from app.print_audit import batch_audit, unknown_attribution
from app.printer_status import status_record
from app.queue import EMPTY_TAPE_BLOCKER, resolve_batch
from app.render import render_document, render_job
from app.reservations import reserve_flush
from app.schemas import (
    ActiveTapeInput,
    AutomaticPrintingInput,
    CartridgeInput,
    CopySelectionInput,
    ImageJobInput,
    JobInput,
    ProfileInput,
    RemainingInput,
    ReminderInput,
    ReviewInput,
)
from app.submissions import (
    build_job,
    input_fingerprint,
    rendering_spec,
    save_submission,
    submission_destination,
    submitted_job,
)
from app.template_schema import PreviewInput, TemplateDocument, TemplateInput
from app.templates import template_record

router = APIRouter(prefix="/api")


@router.get("/status")
def status(
    request: Request,
    session: Session = Depends(db, scope="function"),
    printer_id: str | None = None,
) -> dict[str, Any]:
    return status_record(request, session, printer_id)


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
    from app.request_models import PrintRequest

    if any(
        label["profile_id"] == identifier
        for pending in session.scalars(select(PrintRequest))
        for label in pending.labels
    ):
        raise HTTPException(409, "Profile is used by a saved print request")
    for query in [
        select(Cartridge.id).where(Cartridge.profile_id == identifier),
        select(PrintJob.id).where(PrintJob.profile_id == identifier),
        select(Notification.id).where(Notification.profile_id == identifier),
        select(PrintRun.id).where(PrintRun.profile_id == identifier),
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
    # Inventory is shared, but physical printer identities may be restricted.
    installed = {
        state.active_cartridge_id: state.printer_id
        for state in session.scalars(select(PrinterState))
        if state.active_cartridge_id
    }
    busy_printers = set(
        session.scalars(
            select(Batch.printer_id).where(Batch.state.in_([State.PRINTING, State.NEEDS_REVIEW]))
        )
    )
    return [
        {
            **record(cartridge),
            "installed": cartridge.id in installed,
            "estimate_locked": installed.get(cartridge.id) in busy_printers,
        }
        for cartridge in session.scalars(select(Cartridge))
    ]


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
    installed_states = list(
        session.scalars(select(PrinterState).where(PrinterState.active_cartridge_id == identifier))
    )
    for state in installed_states:
        idle(session, state.printer_id)
    cartridge = get(session, Cartridge, identifier)
    if body.remaining_mm > cartridge.nominal_length_mm:
        raise HTTPException(422, "Remaining length exceeds nominal length")
    cartridge.remaining_mm = body.remaining_mm
    cartridge.consumption_uncertain = False
    if body.remaining_mm > 0:
        for state in installed_states:
            clear_empty_cartridge_alert(session, state)
            if state.blocker == EMPTY_TAPE_BLOCKER:
                state.blocker = None
    session.flush()
    return record(cartridge)


@router.put("/printer/active-tape")
def active_tape(
    body: ActiveTapeInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
    printer_id: str | None = None,
) -> dict[str, Any]:
    printer_id = resolve_destination(session, printer_id)
    access_context(request).require_destination(printer_id, "full")
    idle(session, printer_id)
    state = printer_state(session, printer_id)
    if state.active_cartridge_id != body.cartridge_id and session.scalar(
        select(FlushRequest.id)
        .where(
            FlushRequest.completed.is_(False),
            (FlushRequest.printer_id == printer_id)
            | (FlushRequest.cartridge_id == body.cartridge_id),
        )
        .limit(1)
    ):
        raise HTTPException(409, "Cancel or finish the pending flush before changing cartridges")
    if body.cartridge_id:
        get(session, Cartridge, body.cartridge_id)
        if session.scalar(
            select(PrinterState.id).where(
                PrinterState.active_cartridge_id == body.cartridge_id,
                PrinterState.printer_id != printer_id,
            )
        ):
            raise HTTPException(409, "Cartridge is already installed in another printer")
    printer_id = resolve_destination(session, printer_id)
    state = printer_state(session, printer_id)
    if state.active_cartridge_id != body.cartridge_id:
        clear_empty_cartridge_alert(session, state)
    state.active_cartridge_id = body.cartridge_id
    state.blocker = None
    session.flush()
    return record(state)


@router.get("/printers")
def printers(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    from app.models import PrinterDevice

    result = []
    definitions = {item.id: item for item in request.app.state.registry.definitions()}
    for device in session.scalars(select(PrinterDevice)):
        if device.config.get("retired") or not access_context(request).can_destination(device.id):
            continue
        definition = definitions.get(device.id)
        result.append(
            {
                **(
                    asdict(definition)
                    if definition
                    else {
                        "id": device.id,
                        "name": device.name,
                        "driver": device.driver,
                        "capabilities": None,
                        "connection": None,
                    }
                ),
                "config": device.config
                if access_context(request).can_destination(device.id, "full")
                else {},
                "configuration_error": request.app.state.fleet.configuration_errors.get(device.id),
            }
        )
    return result


@router.get("/workspace")
def workspace_info(
    request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return {
        "notifications_enabled": notifications_enabled(session),
        "total_queued": session.scalar(
            visible_jobs(
                request, session, select(func.count()).select_from(LabelCopy).join(PrintJob)
            ).where(LabelCopy.state == State.QUEUED)
        ),
    }


@router.get("/user-groups")
def user_groups(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    from app.models import UserGroup

    actor = access_context(request).actor
    return [
        {
            "id": group.id,
            "name": group.name,
            "can_create": actor.is_admin or actor.group_memberships[group.id].can_create,
            "can_edit_others": actor.is_admin or actor.group_memberships[group.id].can_edit_others,
            "can_delete_others": actor.is_admin
            or actor.group_memberships[group.id].can_delete_others,
        }
        for group in session.scalars(select(UserGroup).order_by(UserGroup.name))
        if actor.is_admin or group.id in actor.group_ids
    ]


@router.put("/printer/automatic-printing")
def automatic_printing(
    body: AutomaticPrintingInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
    printer_id: str | None = None,
) -> dict[str, Any]:
    printer_id = resolve_destination(session, printer_id)
    access_context(request).require_destination(printer_id, "moderator")
    state = printer_state(session, printer_id)
    state.automatic_printing_held = body.held
    session.flush()
    return record(state)


@router.get("/templates")
def templates(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return [
        {
            **template_record(t, session),
            "asset_notices": document_notices(session, t.document),
            "can_edit": template_access(request, t, Action.WRITE),
            "can_delete": template_access(request, t, Action.DELETE),
        }
        for t in session.scalars(
            select(LabelTemplate)
            .where(LabelTemplate.archived.is_(False))
            .order_by(LabelTemplate.name)
        )
        if template_access(request, t)
    ]


@router.get("/templates/{identifier}")
def template(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    value = get(session, LabelTemplate, identifier)
    return {
        **template_record(value, session),
        "asset_notices": document_notices(session, value.document),
        "can_edit": template_access(request, value, Action.WRITE),
        "can_delete": template_access(request, value, Action.DELETE),
    }


@router.get("/templates/{identifier}/preview.webp")
def template_thumbnail(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> Response:
    # Serialize with deletion so a cached thumbnail cannot bypass removed dependencies.
    with request.app.state.fleet.lock:
        value = get(session, LabelTemplate, identifier)
        require_document_assets(request, session, value.document, allow_missing=True)
        notices = document_notices(session, value.document)
        try:
            content = request.app.state.template_previews.get(
                value, notices, request.app.state.fonts, request.app.state.images
            )
        except (ValueError, OSError) as error:
            raise HTTPException(422, "Template preview is unavailable") from error
    return Response(content, media_type="image/webp")


def validate_layout(
    document: TemplateDocument, request: Request, destination_id: str | None = None
) -> None:
    try:
        render_document(
            document,
            {},
            rendering_spec(request, document, destination_id),
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
    template_scope(request, session, body.scope, body.group_id)
    with rendering(
        request, session, body.document.model_dump(), destination_id=body.destination_id
    ):
        validate_layout(body.document, request, body.destination_id)
    value = LabelTemplate(
        name=body.name,
        document=body.document.model_dump(),
        owner_id=access_context(request).actor.id,
        scope=body.scope,
        group_id=body.group_id,
    )
    session.add(value)
    session.flush()
    session.add(
        TemplateRevision(
            template_id=value.id, revision=value.revision, name=value.name, document=value.document
        )
    )
    return template_record(value, session)


@router.put("/templates/{identifier}")
def update_template(
    identifier: str,
    body: TemplateInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    value = get(session, LabelTemplate, identifier)
    require_record(request, value, Action.WRITE)
    if (value.scope, value.group_id) != (body.scope, body.group_id):
        template_scope(request, session, body.scope, body.group_id)
        if (
            not access_context(request).actor.is_admin
            and value.owner_id != access_context(request).actor.id
        ):
            raise HTTPException(403, "Only the owner or an administrator can change sharing")
    if value.archived or body.expected_revision != value.revision:
        raise HTTPException(409, "Template changed or was archived; reload before saving")
    with rendering(
        request, session, body.document.model_dump(), destination_id=body.destination_id
    ):
        validate_layout(body.document, request, body.destination_id)
    value.name, value.document = body.name, body.document.model_dump()
    value.scope, value.group_id = body.scope, body.group_id
    value.revision += 1
    request.state.after_commit.append(
        lambda identifier=value.id: request.app.state.template_previews.invalidate(identifier)
    )
    session.add(
        TemplateRevision(
            template_id=value.id, revision=value.revision, name=value.name, document=value.document
        )
    )
    session.flush()
    return template_record(value, session)


@router.delete("/templates/{identifier}")
def archive_template(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    value = get(session, LabelTemplate, identifier)
    require_record(request, value, Action.DELETE)
    value.archived = True
    return {"archived": True}


@router.delete("/templates/{identifier}/permanent")
def delete_template(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    value = get(session, LabelTemplate, identifier)
    context = access_context(request)
    actor = context.actor
    if not actor.is_admin and not (
        value.scope == "global" and context.has_permission("templates.delete_global")
    ):
        raise HTTPException(403, "You cannot delete this template")
    require_record(request, value, Action.DELETE)
    retain(session, "templates", identifier, value.name, value.owner_id, actor.id)
    from app.job_access import reconcile_access_holds

    reconcile_access_holds(session)
    return {"deleted": True}


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
    return preview_record(body, request, session)


def preview_record(body: PreviewInput, request: Request, session: Session) -> dict[str, Any]:
    document = body.document or TemplateDocument.model_validate(
        get(session, LabelTemplate, body.template_id or "").document
    )
    require_document_assets(request, session, document.model_dump(), allow_missing=True)
    foreground = body.foreground or (
        document.preview_tape.foreground if document.preview_tape else "#000000"
    )
    background = body.background or (
        document.preview_tape.background if document.preview_tape else "#ffffff"
    )
    try:
        output = render_document(
            document,
            body.data,
            rendering_spec(request, document, body.destination_id),
            body.use_samples,
            fonts=request.app.state.fonts,
            images=request.app.state.images,
            allow_missing_assets=True,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {
        "png": output.preview(foreground, background),
        "design_png": output.preview(foreground, background, smooth=True),
        "svg": output.svg,
        "pixel_width": output.image.width,
        "pixel_height": output.image.height,
        "warnings": output.warnings,
        "missing_assets": output.missing_assets,
        "printable": not output.missing_assets,
        "length_mm": output.document.length_mm,
        "width_mm": output.document.width_mm,
        "resolved_elements": [e.model_dump() for e in output.document.elements],
    }


@router.post("/jobs", status_code=201)
def create_job(
    body: JobInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    body.destination_id = submission_destination(request, session, body.destination_id)
    access_context(request).require_destination(body.destination_id, "print")
    fingerprint = input_fingerprint(body.model_dump())
    existing = submitted_job(request, session, fingerprint)
    if existing is not None:
        return existing
    profile = get(session, TapeProfile, body.tape_profile)
    template = get(session, LabelTemplate, body.template)
    if template.archived:
        raise HTTPException(409, "Template is archived")
    with rendering(request, session, destination_id=body.destination_id):
        job = build_job(
            body,
            profile,
            template,
            rendering_spec(request, template.document, body.destination_id),
            request.app.state.fonts,
            request.app.state.images,
            context=access_context(request),
        )
    existing = submitted_job(request, session, fingerprint)
    if existing is not None:
        return existing
    return save_submission(request, session, job, fingerprint)


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
            rendering_spec(request, body.model_dump(), body.destination_id),
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
    return preview_record(
        PreviewInput(
            document=document,
            foreground=profile.foreground,
            background=profile.background,
            destination_id=body.destination_id,
        ),
        request,
        session,
    )


@router.post("/image-jobs", status_code=201)
def create_image_job(
    body: ImageJobInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    # Share the key namespace with template submissions, but never their fingerprints.
    body.destination_id = submission_destination(request, session, body.destination_id)
    access_context(request).require_destination(body.destination_id, "print")
    fingerprint = input_fingerprint(body.model_dump(), "image_job")
    existing = submitted_job(request, session, fingerprint)
    if existing is not None:
        return existing
    profile, document = image_job_document(body, request, session)
    with rendering(request, session, body.model_dump(), destination_id=body.destination_id):
        template = LabelTemplate(
            id="image",
            name="Image label",
            revision=1,
            document=document.model_dump(),
            owner_id=access_context(request).actor.id,
        )
        job = build_job(
            JobInput(
                template="image",
                process_name=body.process_name,
                tape_profile=profile.id,
                copies=body.copies,
                data={},
                destination_id=body.destination_id,
            ),
            profile,
            template,
            rendering_spec(request, document, body.destination_id),
            request.app.state.fonts,
            request.app.state.images,
            context=access_context(request),
        )
    existing = submitted_job(request, session, fingerprint)
    if existing is not None:
        return existing
    return save_submission(request, session, job, fingerprint)


@router.get("/jobs")
def list_jobs(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    copy_state: State | None = None,
    profile_id: str | None = None,
    destination_id: str | None = None,
    session: Session = Depends(db, scope="function"),
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    query = visible_jobs(request, session, select(PrintJob))
    if destination_id is not None:
        query = query.where(PrintJob.destination_id == destination_id)
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
    request: Request,
    limit: int = 25,
    offset: int = 0,
    copy_state: State | None = None,
    profile_id: str | None = None,
    destination_id: str | None = None,
    session: Session = Depends(db, scope="function"),
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    query = visible_jobs(request, session, select(PrintJob))
    if destination_id is not None:
        query = query.where(PrintJob.destination_id == destination_id)
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


@router.get("/jobs/{identifier}/preview")
def job_preview(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> Response:
    item = get(session, PrintJob, identifier)
    access_context(request).require(
        Action.READ, Resource("job", item.id, item.owner_id, item.destination_id)
    )
    label = session.scalar(select(LabelCopy).where(LabelCopy.job_id == identifier).limit(1))
    if label is None:
        raise HTTPException(404, "Label copy not found")
    return label_preview_response(request, session, item, label)


def label_preview_response(
    request: Request, session: Session, item: PrintJob, label: LabelCopy
) -> Response:
    try:
        rendered = render_job(
            item,
            label,
            request.app.state.fonts,
            request.app.state.images,
            allow_missing_assets=True,
        )
    except (ValueError, OSError) as error:
        raise HTTPException(422, "Saved label preview is unavailable") from error
    # Use the same packed ink raster as printing, including legacy fixture jobs.
    ink = Image.frombytes("1", (rendered.pixel_width, rendered.pixel_height), rendered.raster)
    profile = get(session, TapeProfile, item.profile_id)
    output = io.BytesIO()
    ImageOps.colorize(ink.convert("L"), black=profile.background, white=profile.foreground).save(
        output, format="PNG"
    )
    return Response(
        output.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/jobs/{identifier}")
def cancel_job(identifier: str, session: Session = Depends(db, scope="function")) -> dict[str, Any]:
    item = get(session, PrintJob, identifier)
    copies = list(session.scalars(select(LabelCopy).where(LabelCopy.job_id == identifier)))
    if not any(c.state == State.QUEUED for c in copies) and any(
        c.state in (State.PRINTING, State.NEEDS_REVIEW) for c in copies
    ):
        raise HTTPException(409, "Use batch review for printing or uncertain copies")
    for label in copies:
        if label.state == State.QUEUED:
            label.state = State.CANCELLED
    session.flush()
    return job_record(session, item)


@router.post("/queue/remove")
def remove_selected(
    body: CopySelectionInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, int]:
    wanted = set(body.copy_ids)
    if len(wanted) != len(body.copy_ids):
        raise HTTPException(422, "Select each copy only once")
    copies = list(session.scalars(select(LabelCopy).where(LabelCopy.id.in_(wanted))))
    if len(copies) != len(wanted) or any(copy.state != State.QUEUED for copy in copies):
        raise HTTPException(409, "Selection changed; refresh the queue before removing items")
    job_ids = {copy.job_id for copy in copies}
    for identifier in job_ids:
        require_record(request, get(session, PrintJob, identifier), Action.WRITE)
    for label in copies:
        label.state = State.CANCELLED
    return {"removed_copies": len(copies)}


@router.post("/queue/print", status_code=202)
def flush_queue(
    body: CopySelectionInput | None = None,
    session: Session = Depends(db, scope="function"),
    printer_id: str | None = None,
    destination_id: str | None = None,
) -> dict[str, Any]:
    return reserve_flush(session, printer_id, destination_id, body)


@router.delete("/queue/flush/{identifier}")
def cancel_flush(
    identifier: str, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    pending = get(session, FlushRequest, identifier)
    if pending.completed:
        raise HTTPException(409, "This flush has already started or completed")
    pending.completed = True
    return {"cancelled": True}


def batch_process_names(session: Session, batch: Batch) -> list[str]:
    names = []
    jobs = session.scalars(
        select(PrintJob)
        .join(LabelCopy, LabelCopy.job_id == PrintJob.id)
        .join(BatchItem, BatchItem.copy_id == LabelCopy.id)
        .where(BatchItem.batch_id == batch.id)
        .order_by(BatchItem.position)
    ).unique()
    for job in jobs:
        name = job.template_snapshot.get("process_name") or job_template_name(session, job)
        if name not in names:
            names.append(name)
    return names


@router.get("/batches")
def batches(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    query = select(Batch)
    if not access_context(request).actor.is_admin:
        query = query.where(
            Batch.printer_id.in_(visible_destinations(request, session, "moderator"))
        )
    return [
        {
            **record(batch),
            **batch_audit(session, batch),
            "process_names": batch_process_names(session, batch),
        }
        for batch in session.scalars(query.order_by(Batch.created_at.desc()).limit(100))
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
        # Physical batch authorization covers every label in this batch, including
        # jobs routed through groups the reviewer cannot otherwise access.
        job = session.get(PrintJob, label.job_id)
        assert job is not None
        items.append(
            {
                **record(item),
                **job_information(session, job, printer_id=batch.printer_id),
                "attribution": item.attribution or unknown_attribution(),
                "job_id": job.id,
                "copy_number": label.ordinal + 1,
                "text": job.payload.get("text") or " · ".join(job.payload.values()) or "Label",
                "width_mm": job.width_mm,
                "length_mm": job.length_mm,
            }
        )
    return {
        **record(batch),
        **batch_audit(session, batch),
        "items": items,
    }


@router.post("/batches/{identifier}/review")
def review(
    identifier: str,
    body: ReviewInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
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
    return {**record(batch), **batch_audit(session, batch)}


@router.get("/batches/{identifier}/items/{copy_id}/preview")
def batch_item_preview(
    identifier: str,
    copy_id: str,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> Response:
    get(session, Batch, identifier)
    if session.get(BatchItem, (identifier, copy_id)) is None:
        raise HTTPException(404, "Batch item not found")
    label = get(session, LabelCopy, copy_id)
    item = session.get(PrintJob, label.job_id)
    assert item is not None
    return label_preview_response(request, session, item, label)


@router.get("/notifications")
def notifications(session: Session = Depends(db, scope="function")) -> list[dict[str, Any]]:
    return [
        {
            **record(n),
            "deliveries": [
                {
                    key: getattr(delivery, key)
                    for key in (
                        "endpoint_name",
                        "attempts",
                        "next_attempt_at",
                        "delivered_at",
                        "cancelled",
                        "last_error",
                    )
                }
                for delivery in session.scalars(
                    select(NotificationDelivery).where(NotificationDelivery.notification_id == n.id)
                )
            ],
        }
        for n in session.scalars(
            select(Notification).order_by(Notification.created_at.desc()).limit(100)
        )
    ]
