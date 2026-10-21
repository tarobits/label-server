"""Administrator-managed notification destinations; never publish during configuration."""

import time
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.admin_api import DB, AdminInput
from app.models import (
    Notification,
    NotificationDelivery,
    NotificationEndpoint,
    PrinterDevice,
    PrinterGroup,
)
from app.notification_routing import refresh_summary
from app.notification_types import (
    DEFAULT_NOTIFICATION_PRIORITIES,
    PRINTER_NOTIFICATION_KINDS,
    NotificationKind,
)

router = APIRouter(prefix="/api/admin/notification-endpoints", tags=["administration"])
Priority = Annotated[int, Field(strict=True, ge=1, le=5)]


class EndpointInput(AdminInput):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)
    topic: str = Field(pattern=r"^[-_A-Za-z0-9]{1,64}$")
    token: str | None = None
    enabled: bool = True
    destination_ids: list[str] = Field(default_factory=list, max_length=1000)
    all_printers: bool = False
    kinds: list[NotificationKind] = Field(min_length=1, max_length=6)
    priorities: dict[NotificationKind, Priority] = Field(
        default_factory=lambda: dict(DEFAULT_NOTIFICATION_PRIORITIES)
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a notification endpoint name")
        return value

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        value = value.strip()
        if (
            any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            or "\\" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("Use an HTTP or HTTPS server URL without query or fragment")
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("Invalid URL")
            parsed.port  # Validate the optional port without opening a connection.
        except ValueError as error:
            raise ValueError("Use an HTTP or HTTPS server URL without credentials") from error
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))

    @model_validator(mode="after")
    def unique_filters(self) -> "EndpointInput":
        for values in (self.destination_ids, self.kinds):
            if len(values) != len(set(values)):
                raise ValueError("Choose each destination and notification kind only once")
        if self.all_printers and self.destination_ids:
            raise ValueError("Choose all current and future printers or specific destinations")
        if (
            not self.all_printers
            and not self.destination_ids
            and PRINTER_NOTIFICATION_KINDS.intersection(self.kinds)
        ):
            raise ValueError("Select printers or distribution groups for printer notifications")
        self.priorities = {**DEFAULT_NOTIFICATION_PRIORITIES, **self.priorities}
        return self


def validate_references(session: Session, body: EndpointInput) -> None:
    for identifier in body.destination_ids:
        device = session.get(PrinterDevice, identifier)
        group = session.get(PrinterGroup, identifier)
        if (device is None or device.config.get("retired")) and group is None:
            raise HTTPException(422, "Choose existing, active printers or distribution groups")


def endpoint_record(endpoint: NotificationEndpoint) -> dict[str, Any]:
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "url": endpoint.url,
        "topic": endpoint.topic,
        "has_token": bool(endpoint.token),
        "enabled": endpoint.enabled,
        "destination_ids": endpoint.destination_ids,
        "all_printers": endpoint.all_printers,
        "kinds": endpoint.kinds,
        "priorities": endpoint.priorities,
        "revision": endpoint.revision,
        "created_at": endpoint.created_at,
    }


def existing_endpoint(session: Session, identifier: str) -> NotificationEndpoint:
    endpoint = session.get(NotificationEndpoint, identifier)
    if endpoint is None or endpoint.deleted_at is not None:
        raise HTTPException(404, "Notification endpoint not found")
    return endpoint


def cancel_pending(session: Session, identifier: str) -> None:
    notice_ids = list(
        session.scalars(
            select(NotificationDelivery.notification_id).where(
                NotificationDelivery.endpoint_id == identifier,
                NotificationDelivery.delivered_at.is_(None),
                NotificationDelivery.cancelled.is_(False),
            )
        )
    )
    session.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.endpoint_id == identifier,
            NotificationDelivery.delivered_at.is_(None),
            NotificationDelivery.cancelled.is_(False),
        )
        .values(cancelled=True)
    )
    for notice in session.scalars(select(Notification).where(Notification.id.in_(notice_ids))):
        refresh_summary(session, notice)


@router.get("")
def list_endpoints(session: DB) -> list[dict[str, Any]]:
    return [
        endpoint_record(endpoint)
        for endpoint in session.scalars(
            select(NotificationEndpoint)
            .where(NotificationEndpoint.deleted_at.is_(None))
            .order_by(NotificationEndpoint.created_at, NotificationEndpoint.id)
        )
    ]


@router.post("", status_code=201)
def create_endpoint(body: EndpointInput, session: DB) -> dict[str, Any]:
    validate_references(session, body)
    values = body.model_dump(exclude={"token"})
    endpoint = NotificationEndpoint(**values, token=body.token or "")
    session.add(endpoint)
    session.flush()
    return endpoint_record(endpoint)


@router.put("/{identifier}")
def update_endpoint(identifier: str, body: EndpointInput, session: DB) -> dict[str, Any]:
    endpoint = existing_endpoint(session, identifier)
    validate_references(session, body)
    values = body.model_dump(exclude={"token"})
    if body.token is not None:
        values["token"] = body.token
    # Filter order has no meaning; retaining it should not cancel pending delivery.
    changed = any(
        set(getattr(endpoint, key)) != set(value)
        if key in ("destination_ids", "kinds")
        else getattr(endpoint, key) != value
        for key, value in values.items()
    )
    if changed:
        for key, value in values.items():
            setattr(endpoint, key, value)
        endpoint.revision += 1
        cancel_pending(session, identifier)
    session.flush()
    return endpoint_record(endpoint)


@router.delete("/{identifier}", status_code=204)
def delete_endpoint(identifier: str, session: DB) -> Response:
    endpoint = existing_endpoint(session, identifier)
    endpoint.enabled = False
    endpoint.deleted_at = time.time()
    endpoint.revision += 1
    cancel_pending(session, identifier)
    return Response(status_code=204)
