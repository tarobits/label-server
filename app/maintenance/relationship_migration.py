"""Administrator-only, explicit repairs while all normal work is paused."""

import hashlib
import json
import secrets
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.authn.access import access_context
from app.db import begin_write
from app.maintenance.migration_resources import RESOURCES, allowed_resources, create_resource
from app.models import ReleaseMigration, new_id
from app.schemas import Input
from migrations.relationships_v1 import VERSION, orphan_query, relationships, violations

router = APIRouter(prefix="/api/migration/relationships", tags=["relationship migration"])
# A credential or consent must never acquire a different owner during repair.
REVOKE_ONLY = {
    "auth_sessions",
    "companion_sessions",
    "companion_pins",
    "recovery_tokens",
    "access_change_confirmations",
    "price_quotes",
}


def pending(session: Session) -> bool:
    item = session.get(ReleaseMigration, VERSION)
    return item is not None and item.completed_at is None


def migration_db(request: Request) -> Iterator[Session]:
    with request.app.state.factory() as session:
        actor = access_context(request).actor
        if not actor.is_admin:
            raise HTTPException(403, "Administrator access is required")
        yield session


@contextmanager
def writing(request: Request, session: Session) -> Generator[None]:
    # Acquire and release inside the endpoint's worker, never across dependency
    # yield: waiting requests must not starve the worker needed by the lock owner.
    with request.app.state.fleet.lock:
        if not access_context(request).actor.is_admin:
            raise HTTPException(403, "Administrator access is required")
        begin_write(session)
        session.info["request"] = request
        if not pending(session) or not request.app.state.relationship_maintenance:
            raise HTTPException(409, "Relationship repairs require migration mode")
        try:
            yield
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(409, "This assignment conflicts with an existing record") from error


DB = Annotated[Session, Depends(migration_db, scope="function")]


def relation_for(session: Session, key: str) -> dict[str, Any]:
    for relation in relationships(session.connection()):
        if key == f"{relation['table']}.{relation['column']}":
            return relation
    raise HTTPException(404, "Unknown relationship")


def row_token(table: sa.Table, row: Any, column: str) -> str:
    return hashlib.sha256(
        json.dumps(
            [table.name, column, [row[c.name] for c in table.primary_key], row[column]],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()


def can_clear(table: sa.Table, row: Any, column: str) -> bool:
    # A group-scoped template needs a group; changing its sharing scope belongs
    # to the normal template editor, after the integrity repair is complete.
    return bool(table.c[column].nullable) and not (
        table.name == "label_templates" and column == "group_id" and row["scope"] == "group"
    )


@router.get("")
def status(session: DB) -> dict[str, Any]:
    item = session.get(ReleaseMigration, VERSION)
    return {
        "required": bool(item and item.completed_at is None),
        "ready": bool(item and item.draft.get("ready")),
        "relationships": violations(session.connection())
        if item and item.completed_at is None
        else [],
    }


@router.get("/rows")
def rows(key: str, session: DB, offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    relation = relation_for(session, key)
    child, condition = orphan_query(session.connection(), relation)
    column = relation["column"]
    result = []
    for row in session.execute(
        sa.select(child).where(condition).order_by(*child.primary_key).offset(offset).limit(50)
    ).mappings():
        revoke = child.name in REVOKE_ONLY
        result.append(
            {
                "token": row_token(child, row, column),
                "name": str(row.get("name") or row.get("id") or "Record")
                if not revoke
                else "Credential / consent record",
                "missing": row[column],
                "nullable": can_clear(child, row, column),
                "revoke_only": revoke,
            }
        )
    return result


@router.get("/targets")
def targets(
    key: str, session: DB, search: str = Query("", max_length=128), offset: int = Query(0, ge=0)
) -> list[dict[str, Any]]:
    relation = relation_for(session, key)
    parent = sa.Table(
        relation["parent"], sa.MetaData(), autoload_with=session.connection(), resolve_fks=False
    )
    identifier = parent.c[relation["parent_column"]]
    name = parent.c.get("name")
    if name is None:
        name = parent.c.get("username")
    if name is None:
        name = identifier
    query = sa.select(identifier.label("id"), name.label("name"))
    if search:
        query = query.where(
            sa.or_(
                identifier.contains(search, autoescape=True), name.contains(search, autoescape=True)
            )
        )
    if relation["parent"] == "users":
        query = query.where(parent.c.disabled.is_(False))
    return [
        dict(row)
        for row in session.execute(query.order_by(identifier).offset(offset).limit(50)).mappings()
    ]


class Repair(Input):
    key: str = Field(max_length=150)
    token: str = Field(pattern=r"^[a-f0-9]{64}$")
    target: str | None = Field(default=None, max_length=128)
    revoke: bool = False
    reason: str = Field(min_length=1, max_length=500)


class Creation(Input):
    key: str = Field(max_length=150)
    token: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: str = Field(max_length=100)
    values: dict[str, Any] = Field(max_length=20)
    reason: str = Field(min_length=1, max_length=500)


def creation_context(body: Creation, session: Session) -> None:
    relation = relation_for(session, body.key)
    child, condition = orphan_query(session.connection(), relation)
    if child.name in REVOKE_ONLY or body.kind not in allowed_resources(relation["parent"]):
        raise HTTPException(
            422, "This relationship requires an existing record or backup restoration"
        )
    if not body.reason.strip():
        raise HTTPException(422, "Provide a reason for creating the replacement")
    if not any(
        row_token(child, row, relation["column"]) == body.token
        for row in session.execute(sa.select(child).where(condition)).mappings()
    ):
        raise HTTPException(409, "This reference changed; refresh the migration")


def creation_hash(body: Creation) -> str:
    from app.authn.auth import token_hash

    return token_hash("migration-resource:" + body.model_dump_json())


@router.get("/creation")
def creation_options(key: str, session: DB) -> dict[str, Any]:
    relation = relation_for(session, key)
    kinds = allowed_resources(relation["parent"]) if relation["table"] not in REVOKE_ONLY else set()
    return {
        "parent": relation["parent"],
        "resources": {kind: RESOURCES[kind] for kind in sorted(kinds)},
    }


@router.get("/creation/targets")
def creation_targets(
    key: str, kind: str, session: DB, search: str = Query("", max_length=128)
) -> list[dict[str, Any]]:
    relation = relation_for(session, key)
    if kind not in allowed_resources(relation["parent"]):
        raise HTTPException(422, "Unsupported resource")
    table = sa.Table(kind, sa.MetaData(), autoload_with=session.connection(), resolve_fks=False)
    name = table.c.username if kind == "users" else table.c.name
    query = sa.select(table.c.id, name.label("name"))
    if search:
        query = query.where(
            sa.or_(
                table.c.id.contains(search, autoescape=True), name.contains(search, autoescape=True)
            )
        )
    return [
        dict(row) for row in session.execute(query.order_by(name, table.c.id).limit(50)).mappings()
    ]


@router.post("/creation/preview")
def preview_creation(body: Creation, request: Request, session: DB) -> dict[str, Any]:
    from app.authn.admin_api import state_hash
    from app.authn.auth import token_hash
    from app.models import AccessChangeConfirmation

    with writing(request, session):
        creation_context(body, session)
        fingerprint = state_hash(session)
        with session.begin_nested() as savepoint:
            result = create_resource(
                body.kind, body.values, request, session, preview=True, relationship=body.key
            )
            savepoint.rollback()
        token = secrets.token_urlsafe(32)
        session.execute(
            sa.delete(AccessChangeConfirmation).where(
                AccessChangeConfirmation.expires_at <= time.time()
            )
        )
        session.add(
            AccessChangeConfirmation(
                token_hash=token_hash(token),
                actor_id=access_context(request).actor.id,
                request_hash=creation_hash(body),
                state_hash=fingerprint,
                expires_at=time.time() + 600,
            )
        )
        return {"confirmation_token": token, "name": result["name"], "kind": body.kind}


@router.post("/creation", status_code=201)
def create_replacement(body: Creation, request: Request, session: DB) -> dict[str, Any]:
    from app.authn.admin_api import state_hash
    from app.authn.auth import token_hash
    from app.models import AccessChangeConfirmation

    with writing(request, session):
        creation_context(body, session)
        receipt = session.get(
            AccessChangeConfirmation, token_hash(request.headers.get("x-access-confirmation", ""))
        )
        actor = access_context(request).actor
        if (
            receipt is None
            or receipt.actor_id != actor.id
            or receipt.expires_at <= time.time()
            or receipt.request_hash != creation_hash(body)
            or receipt.state_hash != state_hash(session)
        ):
            raise HTTPException(409, "Review the current replacement details before creating it")
        result = create_resource(body.kind, body.values, request, session, relationship=body.key)
        session.delete(receipt)
        item = session.get(ReleaseMigration, VERSION)
        assert item is not None
        item.draft = {"ready": False}
        rule = (AuditRequirement("application", "", "audit.view_all"),)
        append_audit(
            session,
            event_id=new_id(),
            action="migration.resource_created",
            outcome="succeeded",
            occurred_at=time.time(),
            scopes=(AuditScope("global"),),
            fields={
                "actor_id": AuditField(actor.id, rule),
                "resource_kind": AuditField(body.kind, rule),
                "resource_id": AuditField(result["id"], rule),
                "name": AuditField(result["name"], rule),
                "relationship": AuditField(body.key, rule),
                "reason": AuditField(body.reason.strip(), rule),
            },
        )
        return result


@router.post("/repair")
def repair(body: Repair, request: Request, session: DB) -> dict[str, bool]:
    with writing(request, session):
        return apply_repair(body, request, session)


def apply_repair(body: Repair, request: Request, session: Session) -> dict[str, bool]:
    if not body.reason.strip():
        raise HTTPException(422, "Provide a reason for the repair")
    relation = relation_for(session, body.key)
    child, condition = orphan_query(session.connection(), relation)
    column = relation["column"]
    # Tokens identify an exact old assignment; stale screens cannot overwrite a repair.
    row = next(
        (
            row
            for row in session.execute(sa.select(child).where(condition)).mappings()
            if row_token(child, row, column) == body.token
        ),
        None,
    )
    if row is None:
        raise HTTPException(409, "This reference changed; refresh the migration")
    where = sa.and_(*(child.c[c.name] == row[c.name] for c in child.primary_key))
    if child.name in REVOKE_ONLY:
        if not body.revoke or body.target is not None:
            raise HTTPException(422, "Revoke invalid credentials; they cannot be reassigned")
        session.execute(sa.delete(child).where(where))
    else:
        if body.revoke:
            raise HTTPException(422, "This record must be retained and reassigned")
        if body.target is None and not can_clear(child, row, column):
            raise HTTPException(422, "Select an existing replacement")
        if body.target is not None:
            parent = sa.Table(
                relation["parent"],
                sa.MetaData(),
                autoload_with=session.connection(),
                resolve_fks=False,
            )
            target_row = (
                session.execute(
                    sa.select(parent).where(parent.c[relation["parent_column"]] == body.target)
                )
                .mappings()
                .first()
            )
            if target_row is None or relation["parent"] == "users" and target_row.get("disabled"):
                raise HTTPException(422, "Select an existing, enabled replacement")
            if child.name == "locations" and column == "parent_id":
                seen = {row["id"]}
                cursor: str | None = body.target
                while cursor:
                    if cursor in seen:
                        raise HTTPException(422, "Location assignment would create a cycle")
                    seen.add(cursor)
                    cursor = session.scalar(
                        sa.select(child.c.parent_id).where(child.c.id == cursor)
                    )
        session.execute(sa.update(child).where(where).values({column: body.target}))
        if child.name == "companions" and column == "bound_user_id":
            from app.models import Companion, CompanionSession

            session.execute(
                sa.update(Companion)
                .where(Companion.id == row["id"])
                .values(revision=Companion.revision + 1)
            )
            session.execute(
                sa.delete(CompanionSession).where(CompanionSession.companion_id == row["id"])
            )
    item = session.get(ReleaseMigration, VERSION)
    assert item is not None
    item.draft = {"ready": False}
    actor = access_context(request).actor
    rule = (AuditRequirement("application", "", "audit.view_all"),)
    values: dict[str, str | bool] = {
        "actor_id": actor.id,
        "relationship": body.key,
        "record": body.token,
        "previous": str(row[column]),
        "replacement": body.target or "",
        "revoked": body.revoke,
        "reason": body.reason.strip(),
    }
    append_audit(
        session,
        event_id=new_id(),
        action="migration.relationship_repaired",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global"),),
        fields={key: AuditField(value, rule) for key, value in values.items()},
    )
    return {"saved": True}


@router.post("/complete")
def complete(request: Request, session: DB) -> dict[str, bool]:
    with writing(request, session):
        if violations(session.connection()):
            raise HTTPException(409, "Repair every missing reference before finishing")
        item = session.get(ReleaseMigration, VERSION)
        assert item is not None
        item.draft = {"ready": True}
        item.completed_by = access_context(request).actor.id
        return {"restart_required": True}
