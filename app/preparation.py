"""Render immutable inputs outside the mutation lock, then validate before saving."""

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.authorization import rendering_destination
from app.destinations import members
from app.http import record
from app.models import Base, PrinterDevice, PrinterGroup


def image_references(value: Any) -> set[str]:
    if isinstance(value, dict):
        own = {value["image_asset"]} if value.get("image_asset") else set()
        return own | set().union(*(image_references(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(image_references(child) for child in value))
    return set()


@contextmanager
def rendering(
    request: Request, session: Session, *documents: Any, destination_id: str | None = None
) -> Iterator[None]:
    """Only use before mutating records. Concurrent edits return a retryable conflict.

    Ending the read transaction also avoids upgrading a stale SQLite WAL snapshot.
    Refreshing the same ORM objects preserves their identity for subsequent updates.
    Assets are immutable; check references again while deletion is excluded by the lock.
    """
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("Prepare rendering before mutating records")
    from app.access import access_context, authorize_current_request
    from app.asset_access import require_document_assets

    actor_before = access_context(request).actor
    require_document_assets(request, session, list(documents))
    destination_id = rendering_destination(
        request,
        session,
        destination_id,
        allow_unassigned=request.url.path.startswith("/api/templates"),
    )
    # Keep destination records alive as well: group changes may alter the planning backend.
    destination_records: list[Base | None] = []
    if destination_id is not None:
        destination_records.append(session.get(PrinterGroup, destination_id))
        destination_records.extend(
            session.get(PrinterDevice, identifier)
            for identifier in members(session, destination_id)
        )
    inputs = [
        (value, copy.deepcopy(record(value)))
        for value in session.identity_map.values()
        if isinstance(value, Base)
    ]
    require_document_assets(request, session, [values for _, values in inputs])
    assets = image_references([*documents, *[values for _, values in inputs]])
    definitions = request.app.state.registry.definitions()
    session.commit()
    authorize_current_request(request)
    if access_context(request).actor != actor_before:
        raise HTTPException(409, "Access changed during preparation; retry the request")
    request.app.state.fleet.lock.release()
    try:
        yield
    finally:
        request.app.state.fleet.lock.acquire()
    session.commit()
    authorize_current_request(request)
    if access_context(request).actor != actor_before:
        raise HTTPException(409, "Access changed during preparation; retry the request")
    for value, values in inputs:
        identity = tuple(
            values[column.key]
            for column in type(value).__mapper__.primary_key
            if column.key is not None
        )
        if session.get(type(value), identity, populate_existing=True) is None:
            raise HTTPException(409, "Inputs changed during preparation; retry the request")
        session.refresh(value)
        if record(value) != values:
            raise HTTPException(409, "Inputs changed during preparation; retry the request")
    if request.app.state.registry.definitions() != definitions:
        raise HTTPException(
            409, "Printer configuration changed during preparation; retry the request"
        )
    try:
        for identifier in assets:
            request.app.state.images.metadata(identifier)
    except ValueError as error:
        raise HTTPException(
            409, "An image was removed during preparation; choose it again"
        ) from error
    require_document_assets(request, session, [*documents, *[values for _, values in inputs]])
