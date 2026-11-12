"""Resumable, explicit ownership migration; previewing never releases dispatch."""

import json
import secrets
import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import access_context
from app.admin_api import state_hash
from app.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.auth import token_hash
from app.http import db, record
from app.models import (
    AccessChangeConfirmation,
    Batch,
    Cartridge,
    PrinterDevice,
    ReleaseMigration,
    ResourceOwnership,
    Role,
    TapeAllocation,
    UsageAdjustment,
    User,
    new_id,
)
from app.resource_access import legacy_permissions
from app.resource_api import ResourceChange, mutate_with_evidence, objects, rights_for
from app.schemas import Input
from app.transaction_routes import TransactionRouter
from app.usage_accounts import pairwise_report

router = TransactionRouter(prefix="/api/migration", tags=["upgrade migration"])
DB = Annotated[Session, Depends(db, scope="function")]


class MigrationDraft(Input):
    resources: list[ResourceChange] = Field(default_factory=list, max_length=1000)
    adjustment_recipients: dict[str, str] = Field(default_factory=dict, max_length=10000)
    adjustment_allocations: dict[
        str,
        Annotated[
            dict[str, Annotated[int, Field(strict=True, ge=-(10**15), le=10**15)]],
            Field(max_length=1000),
        ],
    ] = Field(default_factory=dict, max_length=10000)
    accept_owner_loss: bool = False


def require_admin(request: Request) -> None:
    if not access_context(request).actor.is_admin:
        raise HTTPException(403, "Administrator access is required")


def migration_record(session: Session) -> ReleaseMigration:
    value = session.get(ReleaseMigration, "0.13.0")
    if value is None:
        raise HTTPException(409, "Upgrade the database before migrating ownership")
    return value


@router.get("")
def status(request: Request, session: DB) -> dict[str, Any]:
    value = migration_record(session)
    result: dict[str, Any] = {"required": value.completed_at is None}
    if not access_context(request).actor.is_admin:
        return result
    return {
        **result,
        "draft": value.draft,
        "adjustments": [record(row) for row in session.scalars(select(UsageAdjustment))],
        "balances": pairwise_report(session),
    }


@router.put("/draft")
def save_draft(body: MigrationDraft, request: Request, session: DB) -> dict[str, Any]:
    require_admin(request)
    value = migration_record(session)
    if value.completed_at is not None:
        raise HTTPException(409, "The migration is already complete")
    value.draft = body.model_dump(exclude_unset=True)
    return {"saved": True}


def fingerprint(session: Session, value: ReleaseMigration) -> str:
    # Include retained accounting evidence as well as access state. This also
    # invalidates a preview if another administrator edits the saved draft.
    return token_hash(
        json.dumps(
            {
                "access": state_hash(session),
                "draft": value.draft,
                "allocations": [
                    record(row)
                    for row in session.scalars(
                        select(TapeAllocation).order_by(
                            TapeAllocation.batch_id, TapeAllocation.user_id
                        )
                    )
                ],
                "adjustments": [
                    record(row)
                    for row in session.scalars(select(UsageAdjustment).order_by(UsageAdjustment.id))
                ],
            },
            sort_keys=True,
        )
    )


def stage_migration(request: Request, session: Session, draft: MigrationDraft) -> None:
    rights = rights_for(request, session)
    seen: set[tuple[str, str]] = set()
    for change in draft.resources:
        key = (change.kind, change.identifier)
        if key in seen:
            raise HTTPException(422, "Assign each resource once")
        seen.add(key)
        if change.kind == "location":
            raise HTTPException(422, "Create locations before assigning inventory")
        mutate_with_evidence(session, request, rights, change)
    for kind in ("printer", "cartridge"):
        for resource in objects(session, kind):
            owner = session.get(User, resource.owner_id) if resource.owner_id else None
            if owner is None or owner.disabled:
                raise HTTPException(422, "Assign an enabled owner to every printer and cartridge")
            from app.ownership import record_ownership

            record_ownership(session, kind, resource, at=0)
            histories = list(
                session.scalars(
                    select(ResourceOwnership).where(
                        ResourceOwnership.kind == kind, ResourceOwnership.resource_id == resource.id
                    )
                )
            )
            if len(histories) == 1:
                histories[0].effective_at = 0
    for allocation in session.scalars(select(TapeAllocation)):
        if allocation.recipient_id is not None:
            continue
        batch = session.get(Batch, allocation.batch_id)
        cartridge = session.get(Cartridge, batch.cartridge_id) if batch else None
        if cartridge is None:
            raise HTTPException(409, "A historical allocation's cartridge is missing")
        owner = session.get(User, cartridge.owner_id)
        assert owner is not None
        allocation.cartridge_id = cartridge.id
        allocation.recipient_id, allocation.recipient_name = owner.id, owner.username
        allocation.charged_micros = allocation.cost_micros
    adjustments = list(
        session.scalars(
            select(UsageAdjustment).order_by(UsageAdjustment.created_at, UsageAdjustment.id)
        )
    )
    if (set(draft.adjustment_recipients) | set(draft.adjustment_allocations)) - {
        row.id for row in adjustments
    }:
        raise HTTPException(422, "An adjustment in the draft no longer exists")
    # Rebuild in payment order so previews and completion produce identical FIFO
    # allocations. Savepoints keep preview assignments out of the live ledger.
    for adjustment in adjustments:
        adjustment.cartridge_allocations = {}
    session.flush()
    for adjustment in adjustments:
        identifier = draft.adjustment_recipients.get(adjustment.id, adjustment.recipient_id)
        recipient = session.get(User, identifier) if identifier else None
        if recipient is None or recipient.disabled:
            raise HTTPException(422, "Choose a recipient for every historical adjustment")
        adjustment.recipient_id, adjustment.recipient_name = recipient.id, recipient.username
        from app.cartridge_debts import repayment_allocations

        selection = draft.adjustment_allocations.get(adjustment.id)
        adjustment.cartridge_allocations = {
            key: str(amount)
            for key, amount in repayment_allocations(
                session,
                adjustment.user_id,
                recipient.id,
                adjustment.currency,
                adjustment.amount_minor * 10000,
                selection,
            ).items()
        }
        session.flush()
        actor = access_context(request).actor
        rule = (AuditRequirement("application", "", "usage.view_others"),)
        append_audit(
            session,
            event_id=new_id(),
            action="migration.adjustment_assigned",
            outcome="succeeded",
            occurred_at=time.time(),
            scopes=(AuditScope("global"),),
            fields={
                "actor_id": AuditField(actor.id, ()),
                "actor_name": AuditField(actor.username, ()),
                "adjustment_id": AuditField(adjustment.id, rule),
                "victim_ids": AuditField([adjustment.user_id, recipient.id], rule),
                "recipient_id": AuditField(recipient.id, rule),
            },
        )
    # Freeze the exact old abilities, including the absence of new audit rights.
    from app.models import PrinterGroup

    groups = set(session.scalars(select(PrinterGroup.id)))
    for role in session.scalars(select(Role)):
        role.permissions = [
            {
                "kind": "destination_permissions",
                "destination_id": grant["destination_id"],
                "permissions": sorted(
                    legacy_permissions(grant["level"], group=grant["destination_id"] in groups)
                ),
            }
            if grant.get("kind") == "destination"
            else grant
            for grant in role.permissions
        ]
    session.flush()


@router.post("/preview")
def preview(request: Request, session: DB) -> dict[str, Any]:
    require_admin(request)
    value = migration_record(session)
    if value.completed_at is not None:
        raise HTTPException(409, "The migration is already complete")
    draft = MigrationDraft.model_validate(value.draft)
    original = fingerprint(session, value)
    from app.resource_api import access_snapshot

    resources = {("printer", row.id) for row in session.scalars(select(PrinterDevice))}
    resources |= {("cartridge", row.id) for row in session.scalars(select(Cartridge))}
    before = access_snapshot(session, resources)
    with session.begin_nested() as savepoint:
        stage_migration(request, session, draft)
        balances = pairwise_report(session)
        from app.cartridge_debts import cartridge_balances

        cartridges = cartridge_balances(session)
        adjustments = [
            record(row)
            for row in session.scalars(
                select(UsageAdjustment).order_by(UsageAdjustment.created_at, UsageAdjustment.id)
            )
        ]
        after = access_snapshot(session, resources)
        savepoint.rollback()
    token = secrets.token_urlsafe(32)
    session.add(
        AccessChangeConfirmation(
            token_hash=token_hash(token),
            actor_id=access_context(request).actor.id,
            request_hash="migration:0.13.0",
            state_hash=original,
            expires_at=time.time() + 600,
        )
    )
    return {
        "confirmation_token": token,
        "balances": balances,
        "cartridge_balances": cartridges,
        "adjustments": adjustments,
        "affected_users": [
            {
                "id": user,
                "name": after[user]["name"],
                "before": before[user]["resources"],
                "after": after[user]["resources"],
            }
            for user in after
            if before[user] != after[user]
        ],
    }


@router.post("/complete")
def complete(request: Request, session: DB) -> dict[str, Any]:
    require_admin(request)
    value = migration_record(session)
    if value.completed_at is not None:
        return {"required": False}
    receipt = session.get(
        AccessChangeConfirmation, token_hash(request.headers.get("x-access-confirmation", ""))
    )
    actor = access_context(request).actor
    if (
        receipt is None
        or receipt.actor_id != actor.id
        or receipt.expires_at <= time.time()
        or receipt.request_hash != "migration:0.13.0"
        or receipt.state_hash != fingerprint(session, value)
    ):
        raise HTTPException(409, "Review the current migration before completing it")
    draft = MigrationDraft.model_validate(value.draft)
    if (
        any(
            g.permission == "cartridge.approve_use"
            for change in draft.resources
            for g in change.grants or []
        )
        and not draft.accept_owner_loss
    ):
        raise HTTPException(422, "Acknowledge that Approve use may reduce cartridge owners' income")
    stage_migration(request, session, draft)
    rule = (AuditRequirement("application", "", "audit.view_all"),)
    append_audit(
        session,
        event_id=new_id(),
        action="migration.completed",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global"),),
        fields={
            "actor_id": AuditField(actor.id, ()),
            "actor_name": AuditField(actor.username, ()),
            "version": AuditField("0.13.0", rule),
            "resource_ids": AuditField(
                [f"{item.kind}:{item.identifier}" for item in draft.resources], rule
            ),
        },
    )
    value.completed_at, value.completed_by = time.time(), actor.id
    session.delete(receipt)
    return {"required": False}
