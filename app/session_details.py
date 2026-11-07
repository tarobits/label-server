"""Session display metadata. Never use client descriptions for authorization."""

import logging
import re
import time
from ipaddress import ip_address
from typing import Any
from urllib.parse import unquote

from fastapi import Request
from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import AuthSession, NotificationEndpoint

logger = logging.getLogger(__name__)


def clean(value: str, limit: int = 200) -> str:
    return "".join(character for character in value if character.isprintable()).strip()[:limit]


def address(value: str) -> str | None:
    try:
        return str(ip_address(value.strip()))
    except ValueError:
        return None


def request_details(request: Request) -> dict[str, Any]:
    ip = address(request.client.host) if request.client else None
    location = None
    # Explicit deployment opt-in: the origin must be accessible only through
    # Cloudflare, which overwrites these headers. Never infer trust from headers.
    if request.app.state.settings.trust_cloudflare_headers:
        forwarded = address(request.headers.get("cf-connecting-ip", ""))
        if forwarded:
            ip = forwarded
            country = request.headers.get("cf-ipcountry", "").upper()
            if re.fullmatch(r"[A-Z]{2}", country) and country not in {"XX", "T1"}:
                parts = [
                    clean(unquote(request.headers.get(header, "")))
                    for header in ("cf-ipcity", "cf-region")
                ]
                location = ", ".join(dict.fromkeys(part for part in [*parts, country] if part))
    return {
        "ip_address": ip,
        "user_agent": clean(request.headers.get("user-agent", ""), 1024) or None,
        "location": location,
    }


def client_description(agent: str | None) -> dict[str, str]:
    """Conservative labels for common browsers; reduced UAs cannot reveal a model."""
    ua = agent or ""
    browser = "Unknown browser"
    for pattern, name in (
        (r"Edg(?:A|iOS)?/([\d.]+)", "Edge"),
        (r"OPR/([\d.]+)", "Opera"),
        (r"SamsungBrowser/([\d.]+)", "Samsung Internet"),
        (r"(?:Firefox|FxiOS)/([\d.]+)", "Firefox"),
        (r"(?:Chrome|CriOS)/([\d.]+)", "Chrome"),
        (r"Version/([\d.]+).*Safari/", "Safari"),
    ):
        if match := re.search(pattern, ua):
            browser = f"{name} {match[1]}"
            break
    os_name, device = "Unknown OS", "Unknown device"
    if "iPhone" in ua or "iPad" in ua or "iPod" in ua:
        device = "iPad" if "iPad" in ua else "iPod" if "iPod" in ua else "iPhone"
        os_name = "iPadOS" if device == "iPad" else "iOS"
        if match := re.search(r"OS ([\d_]+)", ua):
            os_name += " " + match[1].replace("_", ".")
    elif "Android" in ua:
        os_name = "Android"
        if match := re.search(r"Android ([\d.]+)", ua):
            os_name += " " + match[1]
        device = "Android phone" if "Mobile" in ua else "Android tablet"
        if match := re.search(r"Android [^;)]+; (?:[a-z]{2}-[A-Z]{2}; )?([^;)]+)", ua):
            model = match[1].split(" Build/")[0].strip()
            if model not in {"K", "wv"}:
                device = model
    elif "Windows" in ua:
        os_name, device = "Windows", "PC"
    elif "CrOS" in ua:
        os_name, device = "ChromeOS", "Chromebook"
    elif "Macintosh" in ua:
        os_name, device = "macOS", "Mac"
    elif "Linux" in ua:
        os_name, device = "Linux", "Computer"
    return {"browser": browser, "os": os_name, "device": device}


def record_activity(request: Request) -> None:
    key = getattr(request.state, "authenticated_session_hash", None)
    if not key:
        return
    now = time.time()
    # Yield dependencies can retain this lock until the response body is sent.
    # Activity is best-effort: never wait for a request that is waiting for us.
    lock = request.app.state.fleet.lock
    if not lock.acquire(blocking=False):
        return
    try:
        with request.app.state.factory.begin() as session:
            session.execute(
                update(AuthSession)
                .where(
                    AuthSession.token_hash == key,
                    AuthSession.expires_at > now,
                    or_(AuthSession.last_seen_at.is_(None), AuthSession.last_seen_at <= now - 60),
                )
                .values(last_seen_at=now, **request_details(request))
            )
    except SQLAlchemyError:
        # A failed metadata write must not turn a completed mutation into a 500.
        logger.warning("Could not update session activity")
    finally:
        lock.release()


def revoke_session(session: Session, record: AuthSession) -> None:
    from app.notification_api import update_configuration

    for endpoint in session.scalars(
        select(NotificationEndpoint).where(
            NotificationEndpoint.transport == "push",
            NotificationEndpoint.owner_id == record.user_id,
            NotificationEndpoint.push_session_hash == record.token_hash,
        )
    ):
        update_configuration(
            session,
            endpoint,
            {
                "enabled": False,
                "push_subscription": {},
                "deleted_at": time.time(),
                "push_session_hash": None,
            },
        )
    session.delete(record)
