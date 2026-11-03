"""Authenticated installation subscriptions; never expose push credentials in responses."""

import base64
import hashlib
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, ValidationError, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.access import LEVELS
from app.auth import actor_for_user, session_user
from app.auth_api import throttle
from app.models import Notification, NotificationEndpoint
from app.notification_api import (
    NotificationPreferences,
    update_configuration,
    validate_references,
)
from app.push_delivery import (
    ExpiredSubscription,
    active_push_session,
    public_key,
    send_push,
    validate_push_url,
)
from app.recovery_api import RecoveryInput, SubscriptionInput, require_user

router = APIRouter(prefix="/api/auth/push", tags=["push notifications"])


class PushKeys(RecoveryInput):
    p256dh: str = Field(pattern=r"^[A-Za-z0-9_-]{87}=?$")
    auth: str = Field(pattern=r"^[A-Za-z0-9_-]{22}(==)?$")

    @field_validator("p256dh")
    @classmethod
    def valid_point(cls, value: str) -> str:
        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), base64.urlsafe_b64decode(value.rstrip("=") + "=")
        )
        return value


class BrowserSubscription(RecoveryInput):
    endpoint: str = Field(max_length=2048)
    expirationTime: float | None = None
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        return validate_push_url(value)


class RegisterPush(RecoveryInput):
    name: str = Field(min_length=1, max_length=100)
    subscription: BrowserSubscription
    replace_id: str | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a device name")
        return value.strip()


def device_record(session: Session, endpoint: NotificationEndpoint) -> dict[str, Any]:
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "enabled": endpoint.enabled and active_push_session(session, endpoint),
        "all_printers": endpoint.all_printers,
        "destination_ids": endpoint.destination_ids,
        "kinds": endpoint.kinds,
        "printer_kinds": endpoint.printer_kinds,
    }


def owned_device(session: Session, identifier: str, owner: str) -> NotificationEndpoint:
    endpoint = session.get(NotificationEndpoint, identifier)
    if (
        endpoint is None
        or endpoint.owner_id != owner
        or endpoint.transport != "push"
        or endpoint.deleted_at is not None
    ):
        raise HTTPException(404, "Device not found")
    return endpoint


@router.get("")
def push_settings(request: Request) -> dict[str, Any]:
    with request.app.state.factory() as session:
        user = require_user(request, session)
        key = public_key(request.app.state.settings)
        return {
            "public_key": key,
            "devices": [
                device_record(session, endpoint)
                for endpoint in session.scalars(
                    select(NotificationEndpoint)
                    .where(
                        NotificationEndpoint.owner_id == user.id,
                        NotificationEndpoint.transport == "push",
                        NotificationEndpoint.deleted_at.is_(None),
                    )
                    .order_by(NotificationEndpoint.created_at, NotificationEndpoint.id)
                )
            ],
        }


@router.post("", status_code=201)
def register_push(body: RegisterPush, request: Request) -> dict[str, Any]:
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        user = require_user(request, session)
        if not public_key(request.app.state.settings):
            raise HTTPException(409, "Push delivery has not been configured")
        current = session_user(request, session)
        assert current is not None
        identifier = "push:" + hashlib.sha256(body.subscription.endpoint.encode()).hexdigest()
        endpoint = session.get(NotificationEndpoint, identifier)
        previous = (
            owned_device(session, body.replace_id, user.id)
            if body.replace_id and body.replace_id != identifier
            else None
        )
        if endpoint and endpoint.owner_id != user.id:
            raise HTTPException(
                409, "Renew this browser subscription before enabling notifications"
            )
        values = {
            "name": body.name,
            "enabled": True,
            "deleted_at": None,
            "push_subscription": body.subscription.model_dump(exclude={"expirationTime"}),
            "push_session_hash": current[1].token_hash,
        }
        if endpoint is None or endpoint.deleted_at is not None:
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(NotificationEndpoint)
                    .where(
                        NotificationEndpoint.owner_id == user.id,
                        NotificationEndpoint.transport == "push",
                        NotificationEndpoint.deleted_at.is_(None),
                    )
                )
                or 0
            )
            if count - bool(previous) >= 20:
                raise HTTPException(409, "Remove an old device before adding another")
        if endpoint is None:
            endpoint = NotificationEndpoint(
                id=identifier,
                owner_id=user.id,
                transport="push",
                url="",
                topic="",
                kinds=previous.kinds if previous else ["general"],
                all_printers=previous.all_printers if previous else False,
                destination_ids=previous.destination_ids if previous else [],
                printer_kinds=previous.printer_kinds if previous else {},
                **values,
            )
            session.add(endpoint)
        else:
            update_configuration(session, endpoint, values)
        if previous:
            update_configuration(
                session,
                previous,
                {
                    "enabled": False,
                    "deleted_at": time.time(),
                    "push_subscription": {},
                    "push_session_hash": None,
                },
            )
        session.flush()
        result = device_record(session, endpoint)
        session.commit()
        return result


@router.put("/{identifier}", status_code=204)
def save_preferences(identifier: str, body: SubscriptionInput, request: Request) -> None:
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        user = require_user(request, session)
        endpoint = owned_device(session, identifier, user.id)
        if body.enabled and not active_push_session(session, endpoint):
            raise HTTPException(409, "Enable notifications on this device again")
        actor = actor_for_user(session, user)
        if "approval_digest" in body.kinds and not actor.is_admin:
            raise HTTPException(403, "Only administrators can subscribe to pending print requests")
        if any(
            not actor.is_admin
            and LEVELS.get(actor.destination_levels.get(item, "none"), 0) < LEVELS["moderator"]
            for item in {*body.destination_ids, *body.printer_kinds}
        ):
            raise HTTPException(403, "Choose destinations you can moderate")
        try:
            preferences = NotificationPreferences(**body.model_dump())
        except ValidationError as error:
            raise HTTPException(
                422, "Choose valid notification types and printer scopes"
            ) from error
        validate_references(session, preferences)
        update_configuration(session, endpoint, body.model_dump())


@router.delete("/{identifier}", status_code=204)
def remove_device(identifier: str, request: Request) -> None:
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        user = require_user(request, session)
        endpoint = owned_device(session, identifier, user.id)
        update_configuration(
            session,
            endpoint,
            {
                "enabled": False,
                "deleted_at": time.time(),
                "push_subscription": {},
                "push_session_hash": None,
            },
        )


@router.post("/{identifier}/test", status_code=204)
def test_device(identifier: str, request: Request) -> None:
    # A test is deliberately addressed to just this device, independent of event filters.
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        user = require_user(request, session)
        throttle(request, "push-test:" + user.id)
        endpoint = owned_device(session, identifier, user.id)
        if not endpoint.enabled or not active_push_session(session, endpoint):
            raise HTTPException(409, "Enable notifications on this device first")
        session.expunge(endpoint)
    try:
        send_push(
            request.app.state.settings,
            endpoint,
            Notification(
                id="push-test",
                title="Taro's Label Room",
                message="Push notifications are working.",
                path="/#/account",
            ),
        )
    except ExpiredSubscription:
        with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
            current_endpoint = session.get(NotificationEndpoint, identifier)
            if current_endpoint and current_endpoint.revision == endpoint.revision:
                update_configuration(session, current_endpoint, {"enabled": False})
        raise HTTPException(410, "This subscription expired. Enable notifications again.") from None
    except Exception:
        raise HTTPException(502, "Could not send the test notification. Try again.") from None
