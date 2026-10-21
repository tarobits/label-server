"""Cached, server-side stable release checks. Credentials never enter API responses."""

import json
import re
import time
from collections.abc import Callable
from threading import Lock, Thread
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from app import __version__
from app.config import Settings

REPOSITORY = "tarobits/label-server"


def stable_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+[\w.-]+)?", value)
    if not match:
        raise ValueError("Expected a stable semantic version")
    return int(match[1]), int(match[2]), int(match[3])


def fetch_release(settings: Settings) -> str:
    token = settings.github_token.get_secret_value() if settings.github_token else ""
    if settings.github_token_file:
        token = settings.github_token_file.read_text().strip()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "label-server"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", headers=headers)
    with urlopen(request, timeout=5) as response:
        release = json.load(response)
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        raise ValueError("Expected a published stable release")
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        raise ValueError("Missing release tag")
    stable_version(tag)
    return tag


class ReleaseChecker:
    def __init__(self, settings: Settings, fetch: Callable[[], str] | None = None):
        self.enabled = settings.check_for_updates
        self.fetch = fetch or (lambda: fetch_release(settings))
        self.lock = Lock()
        self.next_check = 0.0
        self.checking = False
        self.latest: str | None = None
        self.state = "disabled" if not self.enabled else "checking"

    def refresh(self) -> None:
        try:
            tag = self.fetch()
            stable_version(tag)
        except Exception:
            # Exceptions/HTTP bodies can contain secrets; return only a generic state.
            with self.lock:
                self.state = "unavailable"
                self.next_check = time.monotonic() + 900
                self.checking = False
        else:
            with self.lock:
                self.latest = tag
                self.state = "available"
                self.next_check = time.monotonic() + 3600
                self.checking = False

    def status(self) -> dict[str, Any]:
        with self.lock:
            if self.enabled and not self.checking and time.monotonic() >= self.next_check:
                self.checking = True
                self.state = "checking"
                Thread(target=self.refresh, name="release-check", daemon=True).start()
            latest = self.latest
            return {
                "current_version": __version__,
                "latest_version": latest,
                "update_available": bool(
                    latest and stable_version(latest) > stable_version(__version__)
                ),
                "release_url": (
                    f"https://github.com/{REPOSITORY}/releases/tag/{quote(latest, safe='')}"
                    if latest
                    else None
                ),
                "check_status": self.state,
            }
