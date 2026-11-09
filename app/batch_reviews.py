"""Human outcome corrections and private photo evidence, separate from settlement."""

import base64
import binascii
import io
from collections import Counter
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.access import access_context
from app.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.http import db, get
from app.models import (
    AuthSettings,
    Batch,
    BatchItem,
    BatchReview,
    LabelCopy,
    PrintJob,
    State,
    new_id,
)
from app.notifications import enqueue
from app.schemas import Input
from app.submissions import input_fingerprint

router = APIRouter(prefix="/api/batches", tags=["batch review"])
DB = Annotated[Session, Depends(db, scope="function")]


class MisprintInput(Input):
    request_id: UUID
    copy_ids: list[str] = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_photo: str | None = Field(default=None, max_length=6_666_668)


def evidence_policy(session: Session) -> str:
    settings = session.get(AuthSettings, 1)
    return settings.batch_review_evidence if settings else "optional"


def normalize_photo(session: Session, encoded: str | None) -> str | None:
    policy = evidence_policy(session)
    if policy == "required" and not encoded:
        raise HTTPException(422, "An evidence photo is required for batch reviews")
    if not encoded:
        return None
    if policy == "disabled":
        raise HTTPException(422, "Evidence photos are disabled by the administrator")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 5_000_000:
            raise ValueError("Evidence photos are limited to 5 MB")
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP") or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Choose a still PNG, JPEG or WebP photo")
            if source.width * source.height > 16_000_000 or max(source.size) > 8192:
                raise ValueError(
                    "Evidence photos are limited to 16 megapixels and 8192 pixels per side"
                )
            source.load()
            picture = ImageOps.exif_transpose(source).convert("RGBA")
            picture.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            clean = Image.new("RGB", picture.size, "white")
            clean.paste(picture, mask=picture.getchannel("A"))
            output = io.BytesIO()
            clean.save(output, "JPEG", quality=90)
            return base64.b64encode(output.getvalue()).decode("ascii")
    except (
        binascii.Error,
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        ValueError,
    ) as error:
        message = (
            str(error)
            if isinstance(error, ValueError) and not isinstance(error, binascii.Error)
            else "Evidence photo could not be decoded"
        )
        raise HTTPException(422, message) from error


def repeated_review(
    session: Session, request: Request, identifier: str | None, fingerprint: str
) -> bool:
    if not identifier:
        return False
    existing = session.get(BatchReview, identifier)
    if existing is None:
        return False
    if (
        existing.actor_id != access_context(request).actor.id
        or existing.request_hash != fingerprint
    ):
        raise HTTPException(409, "This review reference already has different instructions")
    return True


def save_review(
    session: Session,
    request: Request,
    batch: Batch,
    *,
    identifier: str | None,
    fingerprint: str,
    kind: str,
    reason: str,
    previous: dict[str, str],
    decisions: dict[str, str],
    photo: str | None,
) -> BatchReview:
    actor = access_context(request).actor
    review = BatchReview(
        id=identifier or new_id(),
        request_hash=fingerprint,
        batch_id=batch.id,
        kind=kind,
        actor_id=actor.id,
        actor_name=actor.username,
        reason=reason,
        previous_outcomes=previous,
        decisions=decisions,
        has_photo=photo is not None,
        photo=photo,
    )
    session.add(review)
    session.flush()
    guard = (AuditRequirement("printer", batch.printer_id, "printer.view_activity"),)
    identifiers = list(decisions)
    # The audit envelope is bounded; a physical batch may span several large jobs.
    for offset in range(0, max(1, len(identifiers)), 1000):
        copy_ids = identifiers[offset : offset + 1000]
        requester_ids = list(
            session.scalars(
                select(PrintJob.owner_id)
                .join(LabelCopy, LabelCopy.job_id == PrintJob.id)
                .where(LabelCopy.id.in_(copy_ids))
            ).unique()
        )
        append_audit(
            session,
            event_id=new_id(),
            action="batch.misprint_reported"
            if kind == "misprint"
            else "batch.review_evidence_saved",
            outcome="succeeded",
            occurred_at=review.created_at,
            scopes=(
                AuditScope("printer", batch.printer_id),
                AuditScope("cartridge", batch.cartridge_id),
            ),
            fields={
                "actor_id": AuditField(actor.id, ()),
                "actor_name": AuditField(actor.username, ()),
                "victim_ids": AuditField(requester_ids, guard),
                "batch_id": AuditField(batch.id, guard),
                "review_id": AuditField(review.id, guard),
                "copy_ids": AuditField(copy_ids, guard),
                "reason": AuditField(reason, guard),
                "has_photo": AuditField(photo is not None, guard),
            },
        )
    return review


def review_records(session: Session, batch_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": review.id,
            "kind": review.kind,
            "actor_name": review.actor_name,
            "created_at": review.created_at,
            "reason": review.reason,
            "decisions": review.decisions,
            "previous_outcomes": review.previous_outcomes,
            "photo_url": f"/api/batches/{batch_id}/reviews/{review.id}/photo"
            if review.has_photo
            else None,
        }
        for review in session.scalars(
            select(BatchReview)
            .options(defer(BatchReview.photo))
            .where(BatchReview.batch_id == batch_id)
            .order_by(BatchReview.created_at, BatchReview.id)
        )
    ]


@router.get("/{identifier}/reviews/{review_id}/photo")
def evidence_photo(identifier: str, review_id: str, request: Request, session: DB) -> Response:
    get(session, Batch, identifier)
    review = session.get(BatchReview, review_id)
    if review is None or review.batch_id != identifier or not review.photo:
        raise HTTPException(404, "Evidence photo not found")
    return Response(
        base64.b64decode(review.photo),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{identifier}/misprints")
def report_misprints(
    identifier: str, body: MisprintInput, request: Request, session: DB
) -> dict[str, Any]:
    batch = get(session, Batch, identifier)
    access_context(request).require_printer(batch.printer_id, "review")
    fingerprint = input_fingerprint(
        {"batch_id": identifier, "kind": "misprint", **body.model_dump(mode="json")}
    )
    if repeated_review(session, request, str(body.request_id), fingerprint):
        return {"id": batch.id, "state": batch.state}
    if batch.state in (State.PRINTING, State.NEEDS_REVIEW) or batch.finished_at is None:
        raise HTTPException(409, "Finish reviewing uncertain output before reporting a misprint")
    if not body.reason.strip():
        raise HTTPException(422, "Describe the misprint")
    selected = set(body.copy_ids)
    if len(selected) != len(body.copy_ids):
        raise HTTPException(422, "Select each copy once")
    items = list(
        session.scalars(
            select(BatchItem).where(BatchItem.batch_id == batch.id, BatchItem.copy_id.in_(selected))
        )
    )
    if len(items) != len(selected):
        raise HTTPException(404, "A selected copy is not part of this batch")
    if any(item.outcome != State.PRINTED for item in items):
        raise HTTPException(409, "Only copies currently marked as printed can be reported")
    labels = [get(session, LabelCopy, item.copy_id) for item in items]
    if any(label.state in (State.QUEUED, State.PRINTING, State.NEEDS_REVIEW) for label in labels):
        raise HTTPException(409, "A selected copy has an active or uncertain attempt")
    photo = normalize_photo(session, body.evidence_photo)
    previous = {item.copy_id: item.outcome.value for item in items}
    for item, label in zip(items, labels, strict=True):
        item.outcome = State.FAILED
        # Older releases reused copy IDs; do not rewrite a newer attempt's state.
        latest = session.scalar(
            select(Batch.id)
            .join(BatchItem, BatchItem.batch_id == Batch.id)
            .where(BatchItem.copy_id == label.id)
            .order_by(Batch.created_at.desc())
            .limit(1)
        )
        if latest == batch.id:
            label.state = State.FAILED
    batch.state = State.FAILED
    review = save_review(
        session,
        request,
        batch,
        identifier=str(body.request_id),
        fingerprint=fingerprint,
        kind="misprint",
        reason=body.reason.strip(),
        previous=previous,
        decisions={item.copy_id: "failed" for item in items},
        photo=photo,
    )
    jobs = Counter(label.job_id for label in labels)
    for job_id, count in jobs.items():
        job = session.get(PrintJob, job_id)
        assert job is not None
        enqueue(
            session,
            "Misprint reported",
            f"{count} previously confirmed copies were reported as misprinted. A retry has not been queued.",
            "/#/queue?state=failed",
            recipient_id=job.owner_id,
            context={"review_id": review.id, "job_id": job.id},
        )
    return {"id": batch.id, "state": batch.state}
