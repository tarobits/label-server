"""Review frozen label submissions before creating executable queue entries."""

import copy
import io
import re
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image, ImageOps
from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.api import image_job_document
from app.asset_access import require_document_assets
from app.authorization import rendering_destination
from app.destinations import members
from app.http import db, get, record
from app.models import AuthSettings, LabelCopy, LabelTemplate, PrintJob, PrintRun, TapeProfile, User
from app.preparation import rendering
from app.print_audit import actor_snapshot, approval_attribution
from app.render import render_job
from app.request_models import PrintRequest, RequestDigest
from app.schemas import ImageJobInput, Input, JobInput
from app.submissions import build_job, input_fingerprint, rendering_spec

router = APIRouter(prefix="/api")


class JobRequestInput(Input):
    kind: Literal["job"]
    input: JobInput


class ImageRequestInput(Input):
    kind: Literal["image"]
    input: ImageJobInput


class RunRequestInput(Input):
    kind: Literal["run"]
    run_id: str


RequestInput = Annotated[
    JobRequestInput | ImageRequestInput | RunRequestInput, Field(discriminator="kind")
]


class RejectionInput(Input):
    reason: str = Field(min_length=1, max_length=1000)


def require_request(request: Request, value: PrintRequest) -> None:
    context = access_context(request)
    if value.owner_id != context.actor.id:
        context.require_destination(value.destination_id, "moderator")


def request_record(session: Session, value: PrintRequest) -> dict[str, Any]:
    owner = session.get(User, value.owner_id)
    return {**record(value), "owner_name": owner.username if owner else value.owner_id}


def frozen_job(job: PrintJob) -> dict[str, Any]:
    return {
        key: copy.deepcopy(getattr(job, key))
        for key in (
            "profile_id",
            "template_id",
            "template_snapshot",
            "payload",
            "width_mm",
            "length_mm",
            "copies",
        )
    }


@router.post("/requests", status_code=201)
def create_request(
    body: RequestInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    context = access_context(request)
    key = request.headers.get("Idempotency-Key")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise HTTPException(422, "Invalid Idempotency-Key")
    fingerprint = input_fingerprint(body.model_dump())

    def existing_request() -> PrintRequest | None:
        query = select(PrintRequest).where(PrintRequest.owner_id == context.actor.id)
        if body.kind == "run":
            query = query.where(
                or_(PrintRequest.run_id == body.run_id, PrintRequest.request_key == key)
                if key
                else PrintRequest.run_id == body.run_id
            )
        elif key:
            query = query.where(PrintRequest.request_key == key)
        else:
            return None
        matches = list(session.scalars(query))
        if len(matches) > 1:
            raise HTTPException(409, "Request key already used for different inputs")
        existing = matches[0] if matches else None
        if existing:
            require_request(request, existing)
            if existing.request_hash != fingerprint:
                raise HTTPException(409, "Request key already used for different inputs")
        return existing

    if existing := existing_request():
        return request_record(session, existing)
    run_id = None
    if body.kind == "run":
        run = get(session, PrintRun, body.run_id)
        if run.owner_id != context.actor.id and not context.actor.is_admin:
            raise HTTPException(403, "Only the owner can submit this draft")
        if run.submitted_at is not None:
            raise HTTPException(409, "Run already submitted")
        run_id, destination = run.id, run.destination_id
        labels = [
            {**copy.deepcopy(row), "profile_id": run.profile_id} for row in run.manifest["rows"]
        ]
        require_document_assets(request, session, labels)
    else:
        source = body.input
        source.destination_id = rendering_destination(request, session, source.destination_id)
        assert source.destination_id is not None
        destination = source.destination_id
        if body.kind == "image":
            profile, document = image_job_document(body.input, request, session)
            template = LabelTemplate(
                id="image",
                name="Image",
                revision=1,
                document=document.model_dump(),
                owner_id=context.actor.id,
            )
            job_input = JobInput(
                process_name=source.process_name,
                template="image",
                tape_profile=profile.id,
                copies=source.copies,
                data={},
                destination_id=destination,
            )
        else:
            profile = get(session, TapeProfile, source.tape_profile)
            template = get(session, LabelTemplate, body.input.template)
            if template.archived:
                raise HTTPException(409, "Template is archived")
            job_input = body.input
        with rendering(request, session, template.document, destination_id=destination):
            job = build_job(
                job_input,
                profile,
                template,
                rendering_spec(request, template.document, destination),
                request.app.state.fonts,
                request.app.state.images,
                context=access_context(request),
            )
        labels = [frozen_job(job)]
    access_context(request).require(
        Action.SUBMIT, Resource("destination", destination, destination_id=destination)
    )
    if existing := existing_request():
        return request_record(session, existing)
    value = PrintRequest(
        owner_id=context.actor.id,
        requested_by=actor_snapshot(context.actor),
        destination_id=destination,
        kind=body.kind,
        run_id=run_id,
        request_key=key,
        request_hash=fingerprint,
        labels=labels,
    )
    session.add(value)
    settings = session.get(AuthSettings, 1)
    if settings and settings.approval_notifications_enabled:
        now = time.time()
        digest = session.get(RequestDigest, 1)
        if digest:
            digest.count += 1
        else:
            session.add(
                RequestDigest(
                    id=1,
                    first_at=now,
                    due_at=now + settings.approval_notification_debounce_seconds,
                    count=1,
                )
            )
    session.flush()
    return request_record(session, value)


@router.get("/requests")
def list_requests(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    context = access_context(request)
    query = select(PrintRequest).order_by(PrintRequest.created_at.desc())
    if not context.actor.is_admin:
        from app.authorization import visible_destinations

        query = query.where(
            or_(
                PrintRequest.owner_id == context.actor.id,
                PrintRequest.destination_id.in_(
                    visible_destinations(request, session, "moderator")
                ),
            )
        )
    return [request_record(session, value) for value in session.scalars(query.limit(200))]


@router.get("/requests/{identifier}")
def show_request(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    value = get(session, PrintRequest, identifier)
    require_request(request, value)
    return request_record(session, value)


@router.get("/requests/{identifier}/labels/{position}/preview")
def request_preview(
    identifier: str,
    position: int,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> Response:
    value = get(session, PrintRequest, identifier)
    require_request(request, value)
    if not 0 <= position < len(value.labels):
        raise HTTPException(404, "Label not found")
    job = PrintJob(**value.labels[position])
    rendered = render_job(
        job,
        LabelCopy(id="preview"),
        request.app.state.fonts,
        request.app.state.images,
        allow_missing_assets=True,
    )
    ink = Image.frombytes("1", (rendered.pixel_width, rendered.pixel_height), rendered.raster)
    output = io.BytesIO()
    ImageOps.invert(ink.convert("L")).save(output, format="PNG")
    return Response(
        output.getvalue(), media_type="image/png", headers={"Cache-Control": "private, no-store"}
    )


def moderator(request: Request, value: PrintRequest) -> str:
    context = access_context(request)
    context.require_destination(value.destination_id, "moderator")
    return context.actor.id


@router.post("/requests/{identifier}/approve")
def approve_request(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    value = get(session, PrintRequest, identifier)
    reviewer = moderator(request, value)
    if value.status == "approved":
        return request_record(session, value)
    if value.status != "pending":
        raise HTTPException(409, "This request was already rejected")
    from app.auth import actor_for_user

    owner = session.get(User, value.owner_id)
    if owner is None or owner.disabled:
        raise HTTPException(409, "The submitter is no longer active")
    actor = actor_for_user(session, owner)
    device_ids = members(session, value.destination_id)
    if not actor.is_admin and actor.destination_levels.get(value.destination_id, "none") == "none":
        raise HTTPException(409, "The submitter no longer has access to this destination")
    if not any(pid in request.app.state.fleet.workers for pid in device_ids):
        raise HTTPException(409, "No configured printer is available at this destination")
    require_document_assets(request, session, value.labels)
    now = time.time()
    jobs = []
    for position, label in enumerate(value.labels):
        profile = get(session, TapeProfile, label["profile_id"])
        if profile.width_mm != label["width_mm"]:
            raise HTTPException(409, "Tape width changed; create a new request")
        job = PrintJob(
            **copy.deepcopy(label),
            owner_id=value.owner_id,
            destination_id=value.destination_id,
            run_id=value.run_id,
            run_position=position if value.run_id else None,
            created_at=now,
            authorization_basis="request",
            attribution=approval_attribution(
                value.requested_by, value.created_at, access_context(request).actor, now, value.id
            ),
        )
        session.add(job)
        session.flush()
        session.add_all(LabelCopy(job_id=job.id, ordinal=i) for i in range(job.copies))
        jobs.append(job.id)
    if value.run_id:
        # A moderator approves the submitted request, not the owner's private
        # authoring draft. The request's frozen run reference is already authorized.
        run = session.get(PrintRun, value.run_id)
        if run is None:
            raise HTTPException(409, "The submitted run no longer exists")
        if run.submitted_at is not None:
            raise HTTPException(409, "Run already submitted")
        run.submitted_at = now
    value.status, value.decided_by, value.decided_at, value.job_ids = (
        "approved",
        reviewer,
        now,
        jobs,
    )
    session.flush()
    return request_record(session, value)


@router.post("/requests/{identifier}/reject")
def reject_request(
    identifier: str,
    body: RejectionInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    value = get(session, PrintRequest, identifier)
    reviewer = moderator(request, value)
    if value.status == "rejected":
        return request_record(session, value)
    if value.status != "pending":
        raise HTTPException(409, "This request was already approved")
    value.status, value.reason, value.decided_by, value.decided_at = (
        "rejected",
        body.reason,
        reviewer,
        time.time(),
    )
    session.flush()
    return request_record(session, value)
