"""Account authentication, session cookies and effective permissions.

Opaque session tokens are never stored in plaintext. Permissions are recalculated
for every request, so membership and account changes take effect immediately.
"""

import hashlib
import hmac
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuthSession, AuthSettings, PrinterDevice, PrinterGroup, Role, User, UserGroup

COOKIE_NAME = "label_session"
SESSION_SECONDS = 7 * 24 * 3600
PERMISSIONS = {
    "templates.create_personal": "Create personal templates",
    "templates.create_global": "Create global templates",
    "templates.edit_global": "Edit other users’ global templates",
    "templates.delete_global": "Delete other users’ global templates",
    "assets.write": "Upload and manage own images and fonts",
    "inventory.manage": "Manage tape profiles and cartridges",
    "printers.manage": "Register printers and create distribution groups",
    "usage.view_others": "View other users’ usage and balances",
    "usage.edit_accounts": "Edit usage accounts",
}
MEMBER_PERMISSIONS = [
    {"kind": "application", "permission": "assets.write"},
    {"kind": "application", "permission": "templates.create_personal"},
]
PASSWORD_SLOTS = BoundedSemaphore(2)
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.access import Actor


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    # OWASP's scrypt alternative: N=2^17, r=8, p=1 (128 MiB).
    with PASSWORD_SLOTS:
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256 << 20)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        with PASSWORD_SLOTS:
            result = hashlib.scrypt(
                password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1, maxmem=256 << 20
            )
        return hmac.compare_digest(result.hex(), expected)
    except (ValueError, TypeError):
        return False


def initialize_auth(factory: sessionmaker[Session], data_dir: Path) -> None:
    """Create a local, restricted first-run secret without claiming old records."""
    with factory.begin() as session:
        if session.get(AuthSettings, 1) is None:
            session.add(AuthSettings(id=1))
        if session.get(Role, "member") is None:
            session.add(Role(id="member", name="Member", permissions=MEMBER_PERMISSIONS))
        administrator = session.get(Role, "administrator")
        if administrator is None:
            session.add(
                Role(id="administrator", name="Administrator", permissions=[], protected=True)
            )
        configured = session.scalar(select(User.id).limit(1)) is not None
    path = data_dir / "auth-setup-token"
    if configured:
        path.unlink(missing_ok=True)
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Keep the token file restricted when reusing it across startup attempts.
        path.chmod(0o600)
    else:
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
    logger.warning("Initial administrator setup token: %s", path.read_text().strip())


def actor_for_user(session: Session, user: User) -> "Actor":
    from app.access import ADMINISTRATOR_ROLE_ID, LEVELS, Actor, GroupMembership

    memberships = {
        group.id: GroupMembership(
            can_create=member.get("can_create", False),
            can_edit_others=member.get("can_edit_others", False),
            can_delete_others=member.get("can_delete_others", False),
        )
        for group in session.scalars(select(UserGroup))
        for member in group.members
        if member["user_id"] == user.id
    }
    roles = list(session.scalars(select(Role).where(Role.id.in_(user.role_ids))))
    administrator = any(role.id == ADMINISTRATOR_ROLE_ID for role in roles)
    permissions: set[str] = set()
    levels: dict[str, str] = {}
    for role in roles:
        for permission in role.permissions:
            if permission["kind"] == "application":
                permissions.add(permission["permission"])
            elif permission["kind"] == "destination":
                identifier, level = permission["destination_id"], permission["level"]
                if LEVELS[level] >= LEVELS.get(levels.get(identifier, "none"), 0):
                    levels[identifier] = level
    devices = {
        device.id
        for device in session.scalars(select(PrinterDevice))
        if not device.config.get("retired")
    }
    destinations = devices | set(session.scalars(select(PrinterGroup.id)))
    levels = {
        identifier: level for identifier, level in levels.items() if identifier in destinations
    }
    if administrator:
        permissions = set(PERMISSIONS)
        levels = {identifier: "full" for identifier in destinations}
        memberships = {
            group.id: GroupMembership(True, True, True)
            for group in session.scalars(select(UserGroup))
        }
    return Actor(
        id=user.id,
        username=user.username,
        is_admin=administrator,
        permissions=frozenset(permissions),
        role_ids=frozenset(user.role_ids),
        group_ids=frozenset(memberships),
        printer_ids=frozenset(
            identifier for identifier in devices if levels.get(identifier, "none") != "none"
        ),
        destination_levels=levels,
        group_memberships=memberships,
    )


def active_administrators(session: Session) -> list[User]:
    return [
        user
        for user in session.scalars(select(User).where(User.disabled.is_(False)))
        if "administrator" in user.role_ids
    ]


def session_user(request: Request, session: Session) -> tuple[User, AuthSession] | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 256:
        return None
    record = session.get(AuthSession, token_hash(token))
    if record is None or record.expires_at <= time.time():
        return None
    user = session.get(User, record.user_id)
    if user is None or user.disabled:
        return None
    return user, record


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Cross-site requests are not permitted")
        return

    def normalized(url: str) -> tuple[str, str | None, int | None]:
        parsed = urlsplit(url)
        return (
            parsed.scheme,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    try:
        allowed = {
            normalized(str(request.base_url)),
            normalized(request.app.state.settings.public_url),
        }
        if normalized(origin) not in allowed:
            raise HTTPException(403, "Cross-site requests are not permitted")
    except ValueError as error:
        raise HTTPException(403, "Invalid request origin") from error


def check_csrf(request: Request, session: AuthSession) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    check_origin(request)
    csrf = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(csrf.encode(), session.csrf_token.encode()):
        raise HTTPException(403, "Missing or invalid CSRF token")


def session_record(session: Session, user: User, record: AuthSession) -> dict[str, Any]:
    actor = actor_for_user(session, user)
    settings = session.get(AuthSettings, 1)
    return {
        "setup_required": False,
        "registration_code_required": settings.registration_code_required if settings else True,
        "user": {
            "id": user.id,
            "username": user.username,
            "is_admin": actor.is_admin,
            "permissions": sorted(actor.permissions),
            "group_ids": sorted(actor.group_ids),
            "printer_ids": sorted(actor.printer_ids),
            "role_ids": sorted(actor.role_ids),
            "destination_levels": dict(actor.destination_levels),
            "group_memberships": {
                identifier: {
                    "can_create": membership.can_create,
                    "can_edit_others": membership.can_edit_others,
                    "can_delete_others": membership.can_delete_others,
                }
                for identifier, membership in actor.group_memberships.items()
            },
        },
        "csrf_token": record.csrf_token,
    }


def new_session(
    request: Request, response: Response, session: Session, user: User
) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    record = AuthSession(
        token_hash=token_hash(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=time.time() + SESSION_SECONDS,
    )
    previous = request.cookies.get(COOKIE_NAME)
    if previous:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(previous)))
    session.execute(delete(AuthSession).where(AuthSession.expires_at <= time.time()))
    session.add(record)
    session.flush()
    secure = request.url.scheme == "https" or request.app.state.settings.public_url.startswith(
        "https:"
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return session_record(session, user, record)


class AuthRateLimiter:
    """Bounded, process-local throttling; deployment uses one server process."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, request: Request, username: str) -> None:
        host = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self.lock:
            for key in list(self.events):
                while self.events[key] and self.events[key][0] <= now - 300:
                    self.events[key].popleft()
                if not self.events[key]:
                    del self.events[key]
            keys = [(f"ip:{host}", 60), (f"user:{username.casefold()}", 10)]
            if len(self.events) > 10000 or any(
                len(self.events[key]) >= limit for key, limit in keys
            ):
                raise HTTPException(
                    429,
                    "Too many authentication attempts; try again later",
                    headers={"Retry-After": "300"},
                )
            for key, _ in keys:
                self.events[key].append(now)
