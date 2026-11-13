"""Restricted resource creation for the relationship repair screen.

Only new ordinary resources are supported. No grants, historical records,
caller-selected identifiers, or credential ownership can be manufactured here.
The regular input models and creation/validation routines remain authoritative.
"""

from typing import Any

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.i18n import Message


def field(key: str, label: str, kind: str = "text", **options: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": kind, **options}


NAME = field("name", "Name", required=True, maxlength=100)
RESOURCES: dict[str, dict[str, Any]] = {
    "users": {
        "label": "User",
        "note": "New users have no roles. Assign access after maintenance.",
        "fields": [
            field("username", "Username", required=True, minlength=3, maxlength=64),
            field("password", "Password", "password", required=True, minlength=12, maxlength=256),
        ],
    },
    "user_groups": {
        "label": "Permission group",
        "note": "New groups have no members.",
        "fields": [NAME],
    },
    "locations": {"label": "Location", "fields": [NAME]},
    "tape_profiles": {
        "label": "Tape profile",
        "fields": [
            NAME,
            field("width_mm", "Width (mm)", "number", required=True, min=0.1, max=100),
            field(
                "media_family",
                "Media",
                "select",
                default="tze",
                options=[
                    {"id": "tze", "name": "Continuous TZe"},
                    {"id": "fixed_label", "name": "Fixed labels"},
                ],
            ),
            field("label_length_mm", "Fixed label length (mm)", "number", min=10, max=300),
            field("foreground", "Text color", "color", default="#000000"),
            field("background", "Tape color", "color", default="#ffffff"),
        ],
    },
    "cartridges": {
        "label": "Cartridge",
        "fields": [
            NAME,
            field(
                "profile_id", "Tape profile", "reference", resource="tape_profiles", required=True
            ),
            field(
                "nominal_length_mm",
                "Nominal length (mm)",
                "number",
                required=True,
                min=0.1,
                max=1000000,
            ),
            field(
                "remaining_mm", "Remaining length (mm)", "number", required=True, min=0, max=1000000
            ),
            field(
                "price_minor",
                "Price (minor currency units)",
                "number",
                min=0,
                max=1000000000,
                step=1,
            ),
            field("currency", "Currency", default="EUR", maxlength=3),
        ],
    },
    "printers": {
        "label": "Printer",
        "note": "Registers a main-server printer. Move it to a companion after maintenance if needed.",
        "fields": [
            NAME,
            field("driver", "Driver", default="brother-pt-p710bt", required=True, maxlength=100),
            field("usb_serial", "USB serial", maxlength=128),
            field(
                "resolution",
                "Resolution",
                "select",
                default="normal",
                options=[{"id": "normal", "name": "Normal"}, {"id": "high", "name": "High"}],
            ),
            field("no_automatic_printing", "No automatic printing", "checkbox", default=True),
        ],
    },
    "companions": {
        "label": "Companion",
        "note": "New companions have no access grants or active key. Configure access and issue a key after maintenance.",
        "fields": [
            NAME,
            field("location_id", "Location", "reference", resource="locations", required=True),
        ],
    },
    "billing_accounts": {"label": "Group account", "fields": [NAME]},
}


def allowed_resources(parent: str) -> set[str]:
    if parent not in RESOURCES:
        return set()
    allowed = {parent}
    for entry in RESOURCES[parent]["fields"]:
        if entry.get("resource"):
            allowed |= allowed_resources(entry["resource"])
    return allowed


def create_resource(
    kind: str,
    values: dict[str, Any],
    request: Request,
    session: Session,
    *,
    preview: bool = False,
    relationship: str = "",
) -> dict[str, Any]:
    spec = RESOURCES[kind]
    if set(values) - {entry["key"] for entry in spec["fields"]}:
        raise HTTPException(422, Message("serverMessages.unsupportedCreationFields"))
    if any(
        isinstance(value, (dict, list)) or isinstance(value, str) and len(value) > 1000
        for value in values.values()
    ):
        raise HTTPException(422, Message("serverMessages.invalidResourceFields"))
    if "name" in values and (not isinstance(values["name"], str) or not values["name"].strip()):
        raise HTTPException(422, Message("serverMessages.enterAName"))
    try:
        if kind in {"users", "user_groups"}:
            from app.authn.admin_api import PreviewInput, apply_change

            result = apply_change(
                session,
                PreviewInput(
                    resource="users" if kind == "users" else "groups",
                    method="POST",
                    payload={
                        **values,
                        **({"role_ids": []} if kind == "users" else {"members": []}),
                    },
                ),
                request,
                preview=preview,
            )
            assert result is not None
        elif kind == "locations":
            from app.authn.resource_api import ResourceChange, apply_resource_change, rights_for
            from app.models import new_id

            item = apply_resource_change(
                session,
                rights_for(request, session),
                ResourceChange(
                    kind="location",
                    identifier=new_id(),
                    **values,
                ),
            )
            session.flush()
            result = {"id": item.id, "name": item.name}
        elif kind == "tape_profiles":
            from app.api import create_profile
            from app.schemas import ProfileInput

            result = create_profile(ProfileInput.model_validate(values), session)
        elif kind == "cartridges":
            from app.api import create_cartridge
            from app.schemas import CartridgeInput

            result = create_cartridge(CartridgeInput.model_validate(values), request, session)
        elif kind == "printers":
            from app.printing.fleet_api import register_printer
            from app.schemas import CreatePrinterInput

            result = register_printer(
                CreatePrinterInput.model_validate({"no_automatic_printing": True, **values}),
                request,
                session,
            )
            if relationship == "printer_state.printer_id":
                from sqlalchemy import delete

                from app.models import PrinterState

                # The retained orphan state will be assigned explicitly. Remove
                # only the newly created empty default to avoid its unique key
                # colliding with that retained state during reassignment.
                session.execute(delete(PrinterState).where(PrinterState.printer_id == result["id"]))
        elif kind == "companions":
            from app.companion.companion_api import CompanionInput, change
            from app.models import Companion, Location

            body = CompanionInput.model_validate(values)
            if session.get(Location, body.location_id) is None:
                raise HTTPException(422, Message("serverMessages.chooseAnExistingLocation"))
            item = Companion(name=body.name, location_id=body.location_id, key_hash=None)
            session.add(item)
            session.flush()
            change(session, item, body)
            result = {"id": item.id, "name": item.name}
        elif kind == "billing_accounts":
            from app.accounts.billing_api import AccountInput, create_account

            result = create_account(AccountInput.model_validate(values), request, session)
        else:
            raise HTTPException(422, Message("serverMessages.restoreHistoricalRecordsFromABackup"))
    except ValidationError as error:
        # Never echo passwords or arbitrary rejected values into responses/logs.
        raise HTTPException(
            422,
            [
                {"loc": ["body", *entry["loc"]], "msg": entry["msg"]}
                for entry in error.errors(include_input=False, include_context=False)
            ],
        ) from error
    return {"id": result["id"], "name": result.get("name") or result.get("username"), "kind": kind}
