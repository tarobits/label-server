"""Failure evidence for explicitly catalogued actions, without request payloads."""

import time

from fastapi import Request
from sqlalchemy import select

from app.audit import AuditField, AuditScope, ScopeKind, append_audit
from app.auth import session_user
from app.models import Batch, PrinterDevice, new_id

# This is an action catalogue, not a traffic logger. Polling never enters it.
# Every entry's successful mutation has a transactional producer in its service.
CATALOGUE: dict[tuple[str, str], tuple[str, ScopeKind, str | None]] = {
    **{
        (method, path): (action, "global", None)
        for method, path, action in (
            ("POST", "/api/auth/setup", "auth.setup_completed"),
            ("POST", "/api/auth/login", "auth.signed_in"),
            ("POST", "/api/auth/register", "auth.registered"),
            ("POST", "/api/auth/logout", "auth.signed_out"),
            ("POST", "/api/auth/password", "auth.password_changed"),
            ("DELETE", "/api/auth/sessions/others", "auth.sessions_revoked"),
            ("DELETE", "/api/auth/sessions/{session_id}", "auth.session_revoked"),
            ("PUT", "/api/auth/email", "auth.email_changed"),
            ("POST", "/api/auth/email/verify", "auth.email_verified"),
            ("POST", "/api/auth/password/forgot", "auth.reset_requested"),
            ("POST", "/api/auth/password/reset", "auth.password_reset"),
            ("PUT", "/api/auth/email/subscription", "auth.subscription_changed"),
            ("POST", "/api/companion/unlock", "companion.unlocked"),
            ("PUT", "/api/companions/account/pin", "account.pin_changed"),
        )
    },
    ("DELETE", "/api/printers/{identifier}"): ("printer.retired", "printer", "identifier"),
    ("POST", "/api/printers/{identifier}/move-to-companion"): (
        "printer.moved_to_companion",
        "printer",
        "identifier",
    ),
    ("GET", "/api/audit"): ("audit.viewed", "global", None),
    ("POST", "/api/batches/{identifier}/review"): ("batch.reviewed", "printer", "batch"),
    ("POST", "/api/batches/{identifier}/retry-offers"): ("retry.requested", "printer", "batch"),
    ("POST", "/api/cartridges"): ("cartridge.created", "global", None),
    ("PUT", "/api/cartridges/{identifier}"): ("cartridge.renamed", "cartridge", "identifier"),
    ("DELETE", "/api/cartridges/{identifier}"): ("cartridge.archived", "cartridge", "identifier"),
    ("POST", "/api/cartridges/{identifier}/restore"): (
        "cartridge.restored",
        "cartridge",
        "identifier",
    ),
    ("DELETE", "/api/cartridges/{identifier}/permanent"): (
        "cartridge.deleted",
        "cartridge",
        "identifier",
    ),
    ("PUT", "/api/cartridges/{identifier}/notes"): (
        "cartridge.notes_changed",
        "cartridge",
        "identifier",
    ),
    ("PUT", "/api/cartridges/{identifier}/price"): (
        "cartridge.price_changed",
        "cartridge",
        "identifier",
    ),
    ("PUT", "/api/cartridges/{identifier}/remaining"): (
        "cartridge.remaining_corrected",
        "cartridge",
        "identifier",
    ),
    ("PUT", "/api/printer/active-tape"): ("cartridge.swapped", "printer", "printer_id"),
    ("PUT", "/api/printers/{identifier}/cartridge-check"): (
        "printer.cartridge_check_changed",
        "printer",
        "identifier",
    ),
    ("PUT", "/api/printer/automatic-printing"): ("printer.hold_changed", "printer", "printer_id"),
    ("POST", "/api/printers/{identifier}/stop"): (
        "printer.stop_requested",
        "printer",
        "identifier",
    ),
}


def record_failed_action(request: Request, status: int) -> None:
    route = request.scope.get("route")
    entry = CATALOGUE.get((request.method, getattr(route, "path", "")))
    if status < 400 or entry is None:
        return
    action, kind, parameter = entry
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        identity = session_user(request, session)
        user = identity[0] if identity else None
        identifier = (
            request.path_params.get(parameter, request.query_params.get(parameter, ""))
            if parameter
            else ""
        )
        if parameter == "batch":
            batch = session.get(Batch, request.path_params.get("identifier"))
            identifier = batch.printer_id if batch else ""
        if parameter == "printer_id" and not identifier:
            printers = list(session.scalars(select(PrinterDevice.id)))
            if len(printers) == 1:
                identifier = printers[0]
        if kind != "global" and (
            not isinstance(identifier, str) or not identifier or len(identifier) > 100
        ):
            kind, identifier = "global", ""
        append_audit(
            session,
            event_id=new_id(),
            action=action,
            outcome="denied" if status in (401, 403) else "failed",
            occurred_at=time.time(),
            scopes=(AuditScope(kind, identifier),),
            fields={
                "actor_id": AuditField(user.id if user else None, ()),
                "actor_name": AuditField(user.username if user else None, ()),
                "source": AuditField("user" if user else "anonymous", ()),
                "status_code": AuditField(status, ()),
            },
        )
