"""Administrator-managed roles and template memberships with confirmed impact previews."""

import json
import secrets
import time
from collections.abc import Iterator
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access import ADMINISTRATOR_ROLE_ID, access_context
from app.auth import PERMISSIONS, actor_for_user, hash_password, token_hash
from app.auth_api import Credentials, Password, Username
from app.db import begin_write
from app.deletion import delete_account, is_deleted, restore_account, restore_content
from app.history_cleanup import duplicate_history, purge_duplicate_history
from app.models import (
    AccessChangeConfirmation,
    AuthSession,
    AuthSettings,
    Cartridge,
    DeletedContent,
    Location,
    PrinterDevice,
    PrinterGroup,
    RecoveryToken,
    RegistrationCode,
    ResourceGrant,
    Role,
    User,
    UserGroup,
)

router = APIRouter(prefix="/api/admin", tags=["administration"])
CONFIRMATION_SECONDS = 300


def admin_session(request: Request) -> Iterator[Session]:
    if not access_context(request).actor.is_admin:
        raise HTTPException(403, "Administrator access is required")
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        if request.method not in ("GET", "HEAD"):
            begin_write(session)
        if not access_context(request).actor.is_admin:
            raise HTTPException(403, "Administrator access is required")
        try:
            yield session
            if request.method not in ("GET", "HEAD"):
                from app.job_access import reconcile_access_holds

                session.flush()
                reconcile_access_holds(session)
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(409, "That name is already in use") from error


DB = Annotated[Session, Depends(admin_session)]


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoryPurgeInput(AdminInput):
    confirmation: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/history/duplicates")
def preview_history_duplicates(session: DB) -> dict[str, Any]:
    return duplicate_history(session).preview()


@router.post("/history/duplicates/purge")
def purge_history_duplicates(body: HistoryPurgeInput, session: DB) -> dict[str, Any]:
    try:
        return purge_duplicate_history(session, body.confirmation)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


class ApplicationPermission(AdminInput):
    kind: Literal["application"]
    permission: Literal[
        "images.create_personal",
        "images.create_global",
        "images.edit_global",
        "images.delete_global",
        "fonts.create_personal",
        "fonts.create_global",
        "fonts.edit_global",
        "fonts.delete_global",
        "inventory.manage",
        "printers.manage",
        "queue.change_printer",
        "usage.view_others",
        "usage.edit_accounts",
        "audit.view_all",
        "locations.manage",
        "printers.edit_all",
        "cartridges.edit_all",
        "templates.create_personal",
        "templates.create_global",
        "templates.edit_global",
        "templates.delete_global",
    ]


class DestinationPermission(AdminInput):
    kind: Literal["destination"]
    destination_id: str
    level: Literal["none", "request", "print", "moderator", "full"]


class DestinationPermissions(AdminInput):
    kind: Literal["destination_permissions"]
    destination_id: str
    permissions: list[str] = Field(max_length=32)
    denied_permissions: list[str] = Field(default_factory=list, max_length=32)


class LocationPermissions(AdminInput):
    kind: Literal["location_permissions"]
    location_id: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(default_factory=list, max_length=64)
    denied_permissions: list[str] = Field(default_factory=list, max_length=64)


PermissionInput = Annotated[
    ApplicationPermission | DestinationPermission | DestinationPermissions | LocationPermissions,
    Field(discriminator="kind"),
]


class RoleInput(AdminInput):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[PermissionInput] = Field(max_length=1000)


class ContentGroupPermissionsInput(AdminInput):
    can_create: bool = False
    can_edit_others: bool = False
    can_delete_others: bool = False


class GroupPermissionsInput(ContentGroupPermissionsInput):
    images: ContentGroupPermissionsInput = Field(default_factory=ContentGroupPermissionsInput)
    fonts: ContentGroupPermissionsInput = Field(default_factory=ContentGroupPermissionsInput)


class MemberInput(GroupPermissionsInput):
    user_id: str


class GroupInput(AdminInput):
    name: str = Field(min_length=1, max_length=100)
    members: list[MemberInput] = Field(default_factory=list, max_length=10000)


class UserInput(AdminInput):
    username: Username | None = None
    disabled: bool
    role_ids: list[str] = Field(max_length=100)
    password: Password | None = None


class CreateUserInput(Credentials):
    model_config = ConfigDict(extra="forbid")
    role_ids: list[str] = Field(default_factory=lambda: ["member"], max_length=100)


class CodeInput(AdminInput):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default=7, ge=1, le=365)
    role_ids: list[str] = Field(default_factory=lambda: ["member"], max_length=100)
    group_ids: list[str] = Field(default_factory=list, max_length=100)
    group_permissions: dict[str, GroupPermissionsInput] = Field(
        default_factory=dict, max_length=100
    )


class SettingsInput(AdminInput):
    registration_code_required: bool
    approval_notification_debounce_seconds: int = Field(default=60, ge=0, le=86400)
    approval_notifications_enabled: bool = True
    batch_review_evidence: Literal["disabled", "optional", "required"] = "optional"


class PreviewInput(AdminInput):
    resource: Literal["roles", "users", "groups"]
    identifier: str | None = None
    method: Literal["POST", "PUT", "DELETE", "RESTORE"]
    payload: dict[str, Any] = Field(default_factory=dict)


def record(value: Any, fields: str) -> dict[str, Any]:
    return {key: getattr(value, key) for key in fields.split()}


def get(session: Session, model: Any, identifier: str | None) -> Any:
    value = session.get(model, identifier) if identifier else None
    if value is None:
        raise HTTPException(404, "Record not found")
    return value


def require_ids(session: Session, model: Any, identifiers: list[str]) -> None:
    if len(set(identifiers)) != len(identifiers):
        raise HTTPException(422, "Duplicate identifiers are not permitted")
    known: set[str] = set(session.scalars(select(model.id).where(model.id.in_(identifiers))))
    if model is User:
        known = {identifier for identifier in known if not is_deleted(session, "users", identifier)}
    if known != set(identifiers):
        raise HTTPException(422, "One or more referenced records do not exist")


def user_record(session: Session, user: User) -> dict[str, Any]:
    actor = actor_for_user(session, user)
    return {
        **record(user, "id username disabled role_ids created_at"),
        "is_admin": actor.is_admin,
        "group_ids": sorted(actor.group_ids),
    }


def effective_users(session: Session) -> dict[str, dict[str, Any]]:
    result = {}
    for user in session.scalars(select(User).order_by(User.username)):
        if is_deleted(session, "users", user.id):
            continue
        actor = actor_for_user(session, user)
        result[user.id] = {
            "id": user.id,
            "username": user.username,
            "disabled": user.disabled,
            "is_admin": actor.is_admin,
            "role_ids": sorted(actor.role_ids),
            "permissions": sorted(actor.permissions),
            "destination_levels": dict(actor.destination_levels) if not user.disabled else {},
            "destination_permissions": {
                key: sorted(value) for key, value in actor.destination_permissions.items() if value
            }
            if not user.disabled
            else {},
            "cartridge_permissions": {
                key: sorted(value) for key, value in actor.cartridge_permissions.items() if value
            }
            if not user.disabled
            else {},
            "group_memberships": {
                identifier: asdict(member) for identifier, member in actor.group_memberships.items()
            }
            if not user.disabled
            else {},
        }
    return result


def state_hash(session: Session) -> str:
    from app.models import Companion, CompanionPrinter

    state = {}
    for model, fields in (
        (User, "id username role_ids disabled"),
        (Role, "id name permissions protected"),
        (UserGroup, "id name members"),
        (PrinterDevice, "id name driver config owner_id location_id"),
        (Companion, "id name location_id bound_user_id revision"),
        (CompanionPrinter, "printer_id companion_id local_id enabled"),
        (Cartridge, "id owner_id location_id"),
        (Location, "id name parent_id owner_id"),
        (ResourceGrant, "principal_kind principal_id scope_kind scope_id permission effect"),
        (PrinterGroup, "id name printer_ids"),
        (DeletedContent, "kind identifier deleted_at purge_after purged_at account_id"),
    ):
        state[model.__tablename__] = [
            record(value, fields)
            for value in session.scalars(select(model).order_by(*model.__mapper__.primary_key))
        ]
    return token_hash(json.dumps(state, sort_keys=True, separators=(",", ":")))


def normalized_payload(change: PreviewInput) -> dict[str, Any]:
    if change.method in ("DELETE", "RESTORE"):
        if (
            change.payload
            or not change.identifier
            or (change.method == "RESTORE" and change.resource != "users")
        ):
            raise HTTPException(422, "Invalid access change")
        return {}
    if (
        change.method == "POST"
        and change.identifier is not None
        or change.method == "PUT"
        and not change.identifier
    ):
        raise HTTPException(422, "Invalid access change identifier")
    model: type[BaseModel]
    if change.resource == "roles":
        model = RoleInput
    elif change.resource == "groups":
        model = GroupInput
    else:
        model = CreateUserInput if change.method == "POST" else UserInput
    from pydantic import ValidationError

    try:
        return model.model_validate(change.payload).model_dump()
    except ValidationError as error:
        raise HTTPException(422, "Invalid access change payload") from error


def change_hash(change: PreviewInput) -> str:
    payload = normalized_payload(change)
    # Password changes never confer access and are not persisted in preview receipts.
    payload.pop("password", None)
    return token_hash(
        json.dumps(
            {
                "resource": change.resource,
                "identifier": change.identifier,
                "method": change.method,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def validate_role(session: Session, body: RoleInput) -> None:
    unique = set()
    for permission in body.permissions:
        if isinstance(permission, (DestinationPermission, DestinationPermissions)):
            target = session.get(PrinterDevice, permission.destination_id) or session.get(
                PrinterGroup, permission.destination_id
            )
            if target is None or isinstance(target, PrinterDevice) and target.config.get("retired"):
                raise HTTPException(422, "Unknown or retired print destination")
            key = ("destination", permission.destination_id)
            if isinstance(permission, DestinationPermissions):
                from app.resource_access import GROUP_PERMISSIONS, PRINTER_PERMISSIONS

                allowed = (
                    GROUP_PERMISSIONS if isinstance(target, PrinterGroup) else PRINTER_PERMISSIONS
                )
                if (
                    set(permission.permissions) & set(permission.denied_permissions)
                    or len(set(permission.denied_permissions)) != len(permission.denied_permissions)
                    or not set(permission.denied_permissions) <= allowed
                    or len(set(permission.permissions)) != len(permission.permissions)
                    or not set(permission.permissions) <= allowed
                ):
                    raise HTTPException(422, "Invalid or duplicate printer permission")
        elif isinstance(permission, LocationPermissions):
            from app.resource_access import CARTRIDGE_PERMISSIONS, PRINTER_PERMISSIONS

            if session.get(Location, permission.location_id) is None:
                raise HTTPException(422, "Unknown location")
            allowed = PRINTER_PERMISSIONS | CARTRIDGE_PERMISSIONS
            if set(permission.permissions) & set(permission.denied_permissions) or any(
                len(values) != len(set(values)) or not set(values) <= allowed
                for values in (permission.permissions, permission.denied_permissions)
            ):
                raise HTTPException(422, "Invalid or conflicting location permissions")
            key = ("location", permission.location_id)
        else:
            key = ("application", permission.permission)
        if isinstance(permission, (DestinationPermissions, LocationPermissions)):
            from app.permission_rules import validate_submission_modes

            try:
                validate_submission_modes(permission.permissions)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        if key in unique:
            raise HTTPException(422, "Duplicate permission scope")
        unique.add(key)


def role_record(session: Session, role: Role) -> dict[str, Any]:
    payload = record(role, "id name permissions protected")
    locations: dict[str, dict[str, Any]] = {}
    for grant in session.scalars(
        select(ResourceGrant)
        .where(
            ResourceGrant.principal_kind == "role",
            ResourceGrant.principal_id == role.id,
            ResourceGrant.scope_kind == "location",
        )
        .order_by(ResourceGrant.scope_id, ResourceGrant.permission)
    ):
        entry = locations.setdefault(
            grant.scope_id,
            {
                "kind": "location_permissions",
                "location_id": grant.scope_id,
                "permissions": [],
                "denied_permissions": [],
            },
        )
        entry["denied_permissions" if grant.effect == "deny" else "permissions"].append(
            grant.permission
        )
    payload["permissions"] = list(role.permissions) + list(locations.values())
    return payload


def save_role_permissions(session: Session, role: Role, body: RoleInput) -> None:
    role.permissions = [
        entry.model_dump()
        for entry in body.permissions
        if not isinstance(entry, LocationPermissions)
    ]
    session.flush()
    session.execute(
        delete(ResourceGrant).where(
            ResourceGrant.principal_kind == "role",
            ResourceGrant.principal_id == role.id,
            ResourceGrant.scope_kind == "location",
        )
    )
    for entry in body.permissions:
        if not isinstance(entry, LocationPermissions):
            continue
        for effect, permissions in (
            ("allow", entry.permissions),
            ("deny", entry.denied_permissions),
        ):
            session.add_all(
                ResourceGrant(
                    principal_kind="role",
                    principal_id=role.id,
                    scope_kind="location",
                    scope_id=entry.location_id,
                    permission=permission,
                    effect=effect,
                )
                for permission in permissions
            )
    session.flush()


def ensure_administrator_remains(session: Session) -> None:
    from app.auth import active_administrators

    session.flush()
    if not active_administrators(session):
        raise HTTPException(409, "Keep at least one enabled Administrator")


def apply_change(
    session: Session, change: PreviewInput, request: Request, *, preview: bool = False
) -> dict[str, Any] | None:
    payload = normalized_payload(change)
    if change.resource == "roles":
        if change.method == "POST":
            body = RoleInput.model_validate(payload)
            validate_role(session, body)
            role = Role(**body.model_dump())
            session.add(role)
        else:
            role = get(session, Role, change.identifier)
            if role.protected or role.id == ADMINISTRATOR_ROLE_ID:
                raise HTTPException(409, "The Administrator role is protected")
            if change.method == "DELETE":
                if role.id == "member":
                    raise HTTPException(409, "The default registration role cannot be deleted")
                models: tuple[Any, ...] = (User, RegistrationCode)
                for model in models:
                    value: Any
                    for value in session.scalars(select(model)):
                        if role.id in value.role_ids:
                            value.role_ids = [
                                identifier for identifier in value.role_ids if identifier != role.id
                            ]
                session.execute(
                    delete(ResourceGrant).where(
                        ResourceGrant.principal_kind == "role",
                        ResourceGrant.principal_id == role.id,
                    )
                )
                session.delete(role)
                ensure_administrator_remains(session)
                return None
            body = RoleInput.model_validate(payload)
            validate_role(session, body)
            role.name, role.permissions = body.name, body.model_dump()["permissions"]
        save_role_permissions(session, role, body)
        return role_record(session, role)
    if change.resource == "groups":
        if change.method == "DELETE":
            group = get(session, UserGroup, change.identifier)
            for code in session.scalars(select(RegistrationCode)):
                code.group_ids = [
                    identifier for identifier in code.group_ids if identifier != group.id
                ]
                code.group_permissions = {
                    identifier: permissions
                    for identifier, permissions in code.group_permissions.items()
                    if identifier != group.id
                }
            session.delete(group)
            session.flush()
            return None
        group_body = GroupInput.model_validate(payload)
        require_ids(session, User, [member.user_id for member in group_body.members])
        if change.method == "POST":
            group = UserGroup(**group_body.model_dump())
            session.add(group)
        else:
            group = get(session, UserGroup, change.identifier)
            group.name, group.members = group_body.name, group_body.model_dump()["members"]
        session.flush()
        return record(group, "id name members")
    if change.method == "DELETE":
        user = get(session, User, change.identifier)
        delete_account(
            session,
            user,
            access_context(request).actor.id,
            request.app.state.fonts,
            request.app.state.images,
        )
        ensure_administrator_remains(session)
        return None
    if change.method == "RESTORE":
        return user_record(session, restore_account(session, change.identifier or ""))
    if change.method == "POST":
        user_body = CreateUserInput.model_validate(payload)
        require_ids(session, Role, user_body.role_ids)
        user = User(
            username=user_body.username,
            password_hash="preview-only" if preview else hash_password(user_body.password),
            role_ids=user_body.role_ids,
        )
        session.add(user)
    else:
        user_update = UserInput.model_validate(payload)
        user = get(session, User, change.identifier)
        if is_deleted(session, "users", user.id):
            raise HTTPException(404, "Account has been deleted")
        require_ids(session, Role, user_update.role_ids)
        if user_update.username is not None:
            if session.scalar(
                select(User.id).where(
                    func.lower(User.username) == user_update.username, User.id != user.id
                )
            ):
                raise HTTPException(409, "That username is not available")
            user.username = user_update.username
        user.disabled, user.role_ids = user_update.disabled, user_update.role_ids
        if user_update.password is not None:
            user.password_hash = "preview-only" if preview else hash_password(user_update.password)
        if user_update.disabled or user_update.password is not None:
            session.execute(delete(RecoveryToken).where(RecoveryToken.user_id == user.id))
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            from app.companion_auth import revoke_sessions

            revoke_sessions(session, user.id)
    ensure_administrator_remains(session)
    return user_record(session, user)


def confirmed_change(
    request: Request, session: Session, change: PreviewInput
) -> dict[str, Any] | None:
    token = request.headers.get("x-access-confirmation", "")
    confirmation = session.get(AccessChangeConfirmation, token_hash(token))
    actor = access_context(request).actor
    if (
        confirmation is None
        or confirmation.actor_id != actor.id
        or confirmation.expires_at <= time.time()
    ):
        raise HTTPException(409, "Preview and confirm this access change first")
    if confirmation.request_hash != change_hash(change) or confirmation.state_hash != state_hash(
        session
    ):
        raise HTTPException(
            409, "Access configuration changed; recalculate the preview before confirming"
        )
    # Consume first: deleting the acting account also removes its other receipts.
    session.delete(confirmation)
    session.flush()
    before = effective_users(session)
    old_role = (
        session.get(Role, change.identifier)
        if change.resource == "roles" and change.identifier
        else None
    )
    old_rules = role_record(session, old_role)["permissions"] if old_role else []
    result = apply_change(session, change, request)
    if change.resource == "roles":
        from app.access_audit import record_role_rules

        record_role_rules(
            session,
            actor,
            change.identifier or (result or {})["id"],
            old_rules,
            (result or {}).get("permissions", []),
        )
    from app.access_audit import record_access_change

    record_access_change(
        session,
        actor,
        change.resource,
        change.method,
        change.identifier or (result or {}).get("id"),
        before,
        effective_users(session),
    )
    return result


@router.post("/access-preview")
def preview_access(body: PreviewInput, request: Request, session: DB) -> dict[str, Any]:
    fingerprint = state_hash(session)
    request_hash = change_hash(body)
    before = effective_users(session)
    with session.begin_nested() as savepoint:
        apply_change(session, body, request, preview=True)
        after = effective_users(session)
        savepoint.rollback()
    token = secrets.token_urlsafe(32)
    expiry = time.time() + CONFIRMATION_SECONDS
    session.execute(
        delete(AccessChangeConfirmation).where(AccessChangeConfirmation.expires_at <= time.time())
    )
    session.add(
        AccessChangeConfirmation(
            token_hash=token_hash(token),
            actor_id=access_context(request).actor.id,
            request_hash=request_hash,
            state_hash=fingerprint,
            expires_at=expiry,
        )
    )
    affected = [
        {
            "id": identifier,
            "username": (after.get(identifier) or before[identifier])["username"],
            "before": before.get(identifier),
            "after": after.get(identifier),
            "changed": before.get(identifier) != after.get(identifier),
        }
        for identifier in sorted(before.keys() | after.keys())
    ]
    return {
        "confirmation_token": token,
        "expires_at": expiry,
        "affected_users": affected,
        "owner_loss_warning": any(
            "cartridge.approve_use" in permissions
            and "cartridge.approve_use"
            not in before.get(user_id, {}).get("cartridge_permissions", {}).get(cartridge_id, [])
            for user_id, rights in after.items()
            for cartridge_id, permissions in rights["cartridge_permissions"].items()
        ),
    }


@router.get("/permissions")
def permissions(session: DB) -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in PERMISSIONS.items()]


@router.get("/users")
def users(session: DB) -> list[dict[str, Any]]:
    return [
        user_record(session, user)
        for user in session.scalars(select(User).order_by(User.username))
        if not is_deleted(session, "users", user.id)
    ]


@router.post("/users", status_code=201)
def create_user(body: CreateUserInput, request: Request, session: DB) -> Any:
    return confirmed_change(
        request, session, PreviewInput(resource="users", method="POST", payload=body.model_dump())
    )


@router.put("/users/{identifier}")
def update_user(identifier: str, body: UserInput, request: Request, session: DB) -> Any:
    return confirmed_change(
        request,
        session,
        PreviewInput(
            resource="users", identifier=identifier, method="PUT", payload=body.model_dump()
        ),
    )


@router.delete("/users/{identifier}", status_code=204)
def delete_user(identifier: str, request: Request, session: DB) -> None:
    confirmed_change(
        request, session, PreviewInput(resource="users", identifier=identifier, method="DELETE")
    )


@router.post("/users/{identifier}/restore")
def restore_user(identifier: str, request: Request, session: DB) -> Any:
    return confirmed_change(
        request, session, PreviewInput(resource="users", identifier=identifier, method="RESTORE")
    )


@router.get("/trash")
def deleted_content(session: DB) -> list[dict[str, Any]]:
    return [
        record(item, "kind identifier name owner_id deleted_at purge_after account_id")
        for item in session.scalars(
            select(DeletedContent)
            .where(DeletedContent.purged_at.is_(None))
            .order_by(DeletedContent.deleted_at.desc())
        )
    ]


@router.post("/trash/{kind}/{identifier}/restore", status_code=204)
def restore_deleted_content(kind: str, identifier: str, session: DB) -> None:
    if kind not in ("images", "fonts", "templates"):
        raise HTTPException(422, "Restore accounts using the account access preview")
    restore_content(session, kind, identifier)


@router.get("/roles")
def roles(session: DB) -> list[dict[str, Any]]:
    return [
        role_record(session, role) for role in session.scalars(select(Role).order_by(Role.name))
    ]


@router.post("/roles", status_code=201)
def create_role(body: RoleInput, request: Request, session: DB) -> Any:
    return confirmed_change(
        request, session, PreviewInput(resource="roles", method="POST", payload=body.model_dump())
    )


@router.put("/roles/{identifier}")
def update_role(identifier: str, body: RoleInput, request: Request, session: DB) -> Any:
    return confirmed_change(
        request,
        session,
        PreviewInput(
            resource="roles", identifier=identifier, method="PUT", payload=body.model_dump()
        ),
    )


@router.delete("/roles/{identifier}", status_code=204)
def delete_role(identifier: str, request: Request, session: DB) -> None:
    confirmed_change(
        request, session, PreviewInput(resource="roles", identifier=identifier, method="DELETE")
    )


@router.get("/groups")
def groups(session: DB) -> list[dict[str, Any]]:
    return [
        record(group, "id name members")
        for group in session.scalars(select(UserGroup).order_by(UserGroup.name))
    ]


@router.post("/groups", status_code=201)
def create_group(body: GroupInput, request: Request, session: DB) -> Any:
    return confirmed_change(
        request, session, PreviewInput(resource="groups", method="POST", payload=body.model_dump())
    )


@router.put("/groups/{identifier}")
def update_group(identifier: str, body: GroupInput, request: Request, session: DB) -> Any:
    return confirmed_change(
        request,
        session,
        PreviewInput(
            resource="groups", identifier=identifier, method="PUT", payload=body.model_dump()
        ),
    )


@router.delete("/groups/{identifier}", status_code=204)
def delete_group(identifier: str, request: Request, session: DB) -> None:
    confirmed_change(
        request, session, PreviewInput(resource="groups", identifier=identifier, method="DELETE")
    )


@router.get("/registration-codes")
def registration_codes(session: DB) -> list[dict[str, Any]]:
    return [
        record(
            code,
            "id name created_at expires_at redeemed_at revoked role_ids group_ids group_permissions",
        )
        for code in session.scalars(
            select(RegistrationCode).order_by(RegistrationCode.created_at.desc())
        )
    ]


@router.post("/registration-codes", status_code=201)
def create_code(body: CodeInput, session: DB) -> dict[str, Any]:
    require_ids(session, Role, body.role_ids)
    require_ids(session, UserGroup, body.group_ids)
    if not set(body.group_permissions).issubset(body.group_ids):
        raise HTTPException(422, "Group permissions require a selected content group")
    if ADMINISTRATOR_ROLE_ID in body.role_ids:
        raise HTTPException(422, "Registration codes cannot grant Administrator")
    secret = secrets.token_urlsafe(32)
    code = RegistrationCode(
        token_hash=token_hash(secret),
        name=body.name,
        role_ids=body.role_ids,
        group_ids=body.group_ids,
        group_permissions={
            identifier: body.group_permissions.get(
                identifier, GroupPermissionsInput(can_create=True)
            ).model_dump()
            for identifier in body.group_ids
        },
        expires_at=time.time() + body.expires_in_days * 86400,
    )
    session.add(code)
    session.flush()
    return {
        **record(
            code,
            "id name created_at expires_at redeemed_at revoked role_ids group_ids group_permissions",
        ),
        "code": secret,
    }


@router.delete("/registration-codes/{identifier}", status_code=204)
def revoke_code(identifier: str, session: DB) -> None:
    get(session, RegistrationCode, identifier).revoked = True


@router.get("/settings")
def settings(session: DB) -> dict[str, Any]:
    return record(
        session.get(AuthSettings, 1),
        "registration_code_required approval_notification_debounce_seconds approval_notifications_enabled batch_review_evidence",
    )


@router.put("/settings")
def update_settings(body: SettingsInput, request: Request, session: DB) -> dict[str, Any]:
    value = session.get(AuthSettings, 1)
    assert value is not None
    previous = value.batch_review_evidence
    for key, item in body.model_dump(exclude_unset=True).items():
        setattr(value, key, item)
    if previous != value.batch_review_evidence:
        from app.action_audit import record_action

        session.info["request"] = request
        record_action(
            session,
            "settings.review_evidence_changed",
            "global",
            "",
            {
                "previous": previous,
                "current": value.batch_review_evidence,
            },
        )
    return settings(session)
