"""Administrator-managed roles and template memberships with confirmed impact previews."""

import json
import secrets
import time
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access import ADMINISTRATOR_ROLE_ID, access_context
from app.auth import PERMISSIONS, actor_for_user, hash_password, token_hash
from app.auth_api import Credentials, Password
from app.deletion import delete_account, is_deleted, restore_account, restore_content
from app.models import (
    AccessChangeConfirmation,
    AuthSession,
    AuthSettings,
    DeletedContent,
    PrinterDevice,
    PrinterGroup,
    RegistrationCode,
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
            session.execute(text("BEGIN IMMEDIATE"))
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


class ApplicationPermission(AdminInput):
    kind: Literal["application"]
    permission: Literal[
        "assets.write",
        "inventory.manage",
        "printers.manage",
        "templates.create_personal",
        "templates.create_global",
        "templates.edit_global",
        "templates.delete_global",
    ]


class DestinationPermission(AdminInput):
    kind: Literal["destination"]
    destination_id: str
    level: Literal["none", "request", "print", "moderator", "full"]


PermissionInput = Annotated[
    ApplicationPermission | DestinationPermission, Field(discriminator="kind")
]


class RoleInput(AdminInput):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[PermissionInput] = Field(max_length=1000)


class MemberInput(AdminInput):
    user_id: str
    can_create: bool = False
    can_edit_others: bool = False
    can_delete_others: bool = False


class GroupInput(AdminInput):
    name: str = Field(min_length=1, max_length=100)
    members: list[MemberInput] = Field(default_factory=list, max_length=10000)


class UserInput(AdminInput):
    disabled: bool
    role_ids: list[str] = Field(max_length=100)
    password: Password | None = None


class CreateUserInput(Credentials):
    model_config = ConfigDict(extra="forbid")
    role_ids: list[str] = Field(default_factory=lambda: ["member"], max_length=100)


class GroupPermissionsInput(AdminInput):
    can_create: bool = False
    can_edit_others: bool = False
    can_delete_others: bool = False


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
            "group_memberships": {
                identifier: {
                    "can_create": member.can_create,
                    "can_edit_others": member.can_edit_others,
                    "can_delete_others": member.can_delete_others,
                }
                for identifier, member in actor.group_memberships.items()
            }
            if not user.disabled
            else {},
        }
    return result


def state_hash(session: Session) -> str:
    state = {}
    for model, fields in (
        (User, "id username role_ids disabled"),
        (Role, "id name permissions protected"),
        (UserGroup, "id name members"),
        (PrinterDevice, "id name driver config"),
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
        if isinstance(permission, DestinationPermission):
            target = session.get(PrinterDevice, permission.destination_id) or session.get(
                PrinterGroup, permission.destination_id
            )
            if target is None or isinstance(target, PrinterDevice) and target.config.get("retired"):
                raise HTTPException(422, "Unknown or retired print destination")
            key = ("destination", permission.destination_id)
        else:
            key = ("application", permission.permission)
        if key in unique:
            raise HTTPException(422, "Duplicate permission scope")
        unique.add(key)


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
                session.delete(role)
                ensure_administrator_remains(session)
                return None
            body = RoleInput.model_validate(payload)
            validate_role(session, body)
            role.name, role.permissions = body.name, body.model_dump()["permissions"]
        session.flush()
        return record(role, "id name permissions protected")
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
        user.disabled, user.role_ids = user_update.disabled, user_update.role_ids
        if user_update.password is not None:
            user.password_hash = "preview-only" if preview else hash_password(user_update.password)
        if user_update.disabled or user_update.password is not None:
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
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
    return apply_change(session, change, request)


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
    return {"confirmation_token": token, "expires_at": expiry, "affected_users": affected}


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
        record(role, "id name permissions protected")
        for role in session.scalars(select(Role).order_by(Role.name))
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
        raise HTTPException(422, "Group permissions require a selected template group")
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
        "registration_code_required approval_notification_debounce_seconds approval_notifications_enabled",
    )


@router.put("/settings")
def update_settings(body: SettingsInput, session: DB) -> dict[str, Any]:
    value = session.get(AuthSettings, 1)
    for key, item in body.model_dump().items():
        setattr(value, key, item)
    return body.model_dump()
