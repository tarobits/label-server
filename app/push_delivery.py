"""Encrypted Web Push delivery. Subscription URLs and keys must never be logged."""

import argparse
import base64
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from app.config import Settings
from app.email_delivery import normalize_email
from app.models import AuthSession, Notification, NotificationEndpoint


class ExpiredSubscription(Exception):
    """The push service has permanently removed this subscription."""


def active_push_session(session: Session, endpoint: NotificationEndpoint) -> bool:
    login = (
        session.get(AuthSession, endpoint.push_session_hash) if endpoint.push_session_hash else None
    )
    return bool(login and login.user_id == endpoint.owner_id and login.expires_at > time.time())


def validate_push_url(value: str) -> str:
    error = "Use a supported browser push subscription"
    if any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError(error)
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    # Exact vendor boundaries prevent user-supplied subscriptions becoming an SSRF proxy.
    trusted = host == "fcm.googleapis.com" or any(
        host == domain or host.endswith("." + domain)
        for domain in ("push.apple.com", "push.services.mozilla.com")
    )
    if (
        parsed.scheme != "https"
        or not trusted
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.strip("/")
    ):
        raise ValueError(error)
    return value


def public_key(settings: Settings) -> str | None:
    if not settings.vapid_private_key_file or not settings.vapid_subject.startswith("mailto:"):
        return None
    try:
        normalize_email(settings.vapid_subject.removeprefix("mailto:"))
        key = serialization.load_pem_private_key(
            settings.vapid_private_key_file.read_bytes(), password=None
        )
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            return None
        raw = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        return None


class PushSession(requests.Session):
    def request(
        self, method: str, url: str | bytes, *args: Any, **kwargs: Any
    ) -> requests.Response:
        validate_push_url(url.decode() if isinstance(url, bytes) else url)
        kwargs["allow_redirects"] = False
        return super().request(method, url, *args, **kwargs)


def send_push(settings: Settings, endpoint: NotificationEndpoint, notice: Notification) -> None:
    if not public_key(settings):
        raise ValueError("Push delivery is not configured")
    validate_push_url(endpoint.push_subscription["endpoint"])
    # Bounded UTF-8 text stays below the encrypted push service payload limit.
    payload = json.dumps(
        {
            "title": notice.title[:100],
            "body": notice.message[:500],
            "path": notice.path[:300] if notice.path.startswith("/#/") else "/#/",
            "tag": notice.id,
        },
        ensure_ascii=False,
    )
    try:
        with PushSession() as transport:
            transport.trust_env = False
            response = webpush(
                subscription_info=endpoint.push_subscription,
                data=payload,
                vapid_private_key=str(settings.vapid_private_key_file),
                vapid_claims={"sub": settings.vapid_subject},
                ttl=300,
                timeout=10,
                requests_session=transport,
            )
            if not 200 <= response.status_code < 300:
                raise ValueError("Push delivery failed")
    except WebPushException as error:
        if error.response is not None and error.response.status_code in (404, 410):
            raise ExpiredSubscription() from None
        raise ValueError("Push delivery failed") from None


def generate_key(path: Path) -> None:
    """Create once; never overwrite the identity existing installations subscribed to."""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(pem)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a persistent Web Push signing key")
    parser.add_argument("--generate-key", type=Path, required=True)
    args = parser.parse_args()
    generate_key(args.generate_key)
    print("Web Push signing key created. Keep it private and include it in your backups.")
