"""Local station session and restricted proxy. Installation credentials stay server-side."""

import fcntl
import hmac
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, Thread
from typing import Any, AsyncGenerator, Literal
from urllib.parse import quote, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.deployment import require_role
from app.printer.base import ControlledPrinterBackend, StopMode
from app.releases import REPOSITORY, release_version, stable_version
from companion.agent import Agent
from companion.config import LocalPrinter, Settings
from companion.journal import Journal
from companion.status_api import status_router

COOKIE = "label_station"
UPDATE_VALIDATION_PROTOCOL = 1
PROXY_PATH = re.compile(
    r"(?:printers|tape-profiles|cartridges|cartridge-quotes|status|printer/(?:active-tape|automatic-printing)|queue/(?:groups|print)|printers/[A-Za-z0-9_-]+(?:/(?:stop|cartridge-check))?|jobs/[A-Za-z0-9_-]+(?:/preview)?|companion/printers/[A-Za-z0-9_-]+/clear)"
)
PACKING_PATH = re.compile(r"batches/(?:page|[A-Za-z0-9_-]+(?:/items/[A-Za-z0-9_-]+/preview)?)")


def available_update(value: Any) -> dict[str, str] | None:
    if not isinstance(value, str):
        return None
    try:
        stable_version(value)
        if release_version(value) <= release_version(__version__):
            return None
    except ValueError:
        return None
    return {
        "version": value,
        "url": f"https://github.com/{REPOSITORY}/releases/tag/{quote(value, safe='')}",
    }


def frontend_build(path: Path) -> str | None:
    """The installed shell identity, also embedded in the running browser page."""
    try:
        shell = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = re.search(r'<meta name="app-build" content="([a-f0-9]{64})"', shell)
    return match.group(1) if match else None


class Unlock(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    pin: SecretStr = Field(min_length=4, max_length=12)


class Stop(BaseModel):
    mode: Literal["after_current", "emergency"]


class PrinterEnabled(BaseModel):
    enabled: bool


class StationSession:
    def __init__(self) -> None:
        self.lock = Lock()
        self.browser_token = ""
        self.remote_token = ""
        self.last_activity = 0.0
        self.operator: dict[str, Any] | None = None
        self.generation = 0
        self.csrf = secrets.token_urlsafe(32)
        self.attempts: deque[float] = deque()

    def clear(self) -> None:
        self.generation += 1
        self.browser_token, self.remote_token, self.operator = "", "", None


def create_app(
    settings: Settings, agent: Agent | None = None, *, start_agent: bool = True
) -> FastAPI:
    require_role("companion")
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = agent.journal if agent else Journal(settings.data_dir / "journal.db")
    agent = agent or Agent(settings, journal)
    station = StationSession()
    assets = Path(__file__).resolve().parent.parent / "frontend" / "dist-companion"
    build = frontend_build(assets / "companion.html")
    update_marker = settings.data_dir / ".update-in-progress"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        with (settings.data_dir / "station.lock").open("a+") as owner:
            try:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another companion process owns this data directory") from error
            journal.recover()

            def activate() -> None:
                # Do not contact the main server or touch printers until rollback is committed.
                while update_marker.exists():
                    if agent.stop.wait(0.25):
                        return
                if not agent.stop.is_set():
                    agent.run()

            thread = Thread(target=activate, name="companion-sync", daemon=True)
            if start_agent:
                thread.start()
            try:
                yield
            finally:
                agent.stop.set()
                await run_in_threadpool(agent.close, sync_threads=(thread,) if start_agent else ())

    app = FastAPI(title="Label Room companion", lifespan=lifespan)
    from app.http_security import HttpSecurity

    app.state.agent, app.state.station = agent, station
    app.include_router(status_router(settings, agent))
    hostname = urlsplit(settings.public_url).hostname or "localhost"
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[hostname, "localhost", "127.0.0.1", "[::1]"]
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: issue[key] for key in ("type", "loc", "msg")} for issue in error.errors()
                ]
            },
        )

    @app.exception_handler(httpx.HTTPError)
    async def remote_error(request: Request, error: httpx.HTTPError) -> JSONResponse:
        if isinstance(error, httpx.HTTPStatusError):
            try:
                return JSONResponse(
                    status_code=error.response.status_code, content=error.response.json()
                )
            except ValueError:
                pass
        return JSONResponse(status_code=503, content={"detail": "The main server is unavailable"})

    @app.middleware("http")
    async def headers(request: Request, call_next: Any) -> Response:
        if update_marker.exists() and request.url.path != "/api/health":
            return JSONResponse(
                status_code=503,
                content={"detail": "Update validation in progress"},
                headers={"Cache-Control": "no-store"},
            )
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not settings.frame_ancestors:
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    def csrf(request: Request) -> None:
        origin = request.headers.get("origin")
        allowed = {settings.public_url.rstrip("/"), str(request.base_url).rstrip("/")}
        if (
            origin
            and origin.rstrip("/") not in allowed
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            raise HTTPException(403, "Cross-site requests are not permitted")
        if not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode(), station.csrf.encode()
        ):
            raise HTTPException(403, "Invalid station CSRF token")

    def current(request: Request, *, touch: bool = False) -> str:
        with station.lock:
            if (
                station.browser_token
                and time.monotonic() - station.last_activity >= settings.lock_timeout_seconds
            ):
                station.clear()
            cookie = request.cookies.get(COOKIE, "")
            if not station.browser_token or not hmac.compare_digest(
                cookie.encode(), station.browser_token.encode()
            ):
                raise HTTPException(401, "Unlock the station to continue")
            if touch:
                station.last_activity = time.monotonic()
            return station.remote_token

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"healthy": True}

    @app.get("/api/station")
    def dashboard(request: Request) -> dict[str, Any]:
        token = None
        try:
            token = current(request)
        except HTTPException:
            pass
        user = None
        with station.lock:
            generation = station.generation
            if token != station.remote_token:
                token = None
        if token and agent.online:
            try:
                user = agent.request("GET", "/api/companion/operator", token=token).json()
                with station.lock:
                    if generation == station.generation and token == station.remote_token:
                        station.operator = user
                    else:
                        token, user = None, None
            except httpx.HTTPError:
                with station.lock:
                    if generation == station.generation and token == station.remote_token:
                        station.clear()
                if token:
                    agent.revoke_session(token)
                token = None
        elif token:
            with station.lock:
                if generation == station.generation and token == station.remote_token:
                    user = station.operator
                else:
                    token = None
        # Operational summaries never contain label content, requester identities,
        # account balances or credentials. Deployment can hide them until unlock.
        printers = [
            {
                "local_id": device.local_id,
                "id": agent.identifiers.get(device.local_id),
                "name": agent.names.get(device.local_id, device.name),
                "no_automatic_printing": agent.dashboards.get(device.local_id, {}).get(
                    "no_automatic_printing"
                ),
                "status": agent.statuses.get(device.local_id, {"connected": False}),
                **(
                    {
                        "dashboard": agent.dashboards.get(device.local_id),
                        "snapshot_age_seconds": max(
                            0, time.monotonic() - agent.dashboard_received[device.local_id]
                        )
                        if device.local_id in agent.dashboard_received
                        else None,
                    }
                    if settings.show_locked_dashboard_details
                    or (
                        user
                        and "printer.view"
                        in user.get("printer_permissions", {}).get(
                            agent.identifiers.get(device.local_id), []
                        )
                    )
                    else {}
                ),
                "blocked": journal.blocked(device.local_id)
                or agent.server_blocked.get(device.local_id, False),
                "printing": bool(
                    agent.threads.get(device.local_id) and agent.threads[device.local_id].is_alive()
                ),
                "can_stop": isinstance(
                    agent.executors[device.local_id].backend, ControlledPrinterBackend
                ),
            }
            for device in agent.devices
        ]
        return {
            "name": agent.users.get("name", "Companion"),
            "version": __version__,
            "update": available_update(agent.users.get("latest_release"))
            if settings.show_update_notice
            else None,
            "frontend_build": build,
            "online": agent.online,
            "locked": token is None,
            "user": user,
            "users": agent.users.get("users", []),
            "single_user_id": settings.single_user_id,
            "printers": printers,
            "removed_printers": [
                {
                    "local_id": device["local_id"],
                    "name": agent.names.get(device["local_id"], device["name"]),
                }
                for device in journal.printers(enabled=False)
            ]
            if user and "printers.manage" in user["permissions"]
            else [],
            "csrf_token": station.csrf,
            "lock_timeout_seconds": settings.lock_timeout_seconds,
            "lock_remaining_seconds": max(
                0.0, settings.lock_timeout_seconds - (time.monotonic() - station.last_activity)
            )
            if token
            else None,
            "pin_keypad": {
                "enabled": settings.pin_keypad_enabled,
                "shuffle": settings.pin_keypad_shuffle,
            },
            "stop_policy": {
                "locked_emergency": settings.allow_locked_emergency_stop,
                "locked_after_current": settings.allow_locked_stop_after_label,
                "offline_emergency": settings.allow_offline_emergency_stop,
                "offline_after_current": settings.allow_offline_stop_after_label,
            },
        }

    @app.get("/api/station/users/{identifier}/avatar")
    def user_avatar(identifier: str) -> Response:
        if not agent.online:
            raise HTTPException(503, "The main server is unavailable")
        if not any(user["id"] == identifier for user in agent.users.get("users", [])):
            raise HTTPException(404, "User is not available at this station")
        # The main server rechecks current station access, including revocations.
        result = agent.request("GET", f"/api/companion/users/{quote(identifier, safe='')}/avatar")
        return Response(result.content, media_type="image/png")

    @app.post("/api/station/unlock")
    def unlock(body: Unlock, request: Request, response: Response) -> dict[str, bool]:
        csrf(request)
        with station.lock:
            now = time.monotonic()
            while station.attempts and station.attempts[0] <= now - 300:
                station.attempts.popleft()
            if len(station.attempts) >= 10:
                raise HTTPException(429, "Too many PIN attempts; try again later")
            station.attempts.append(now)
            station.generation += 1
            generation = station.generation
        pin = body.pin.get_secret_value()
        if settings.single_user_id:
            if (
                body.user_id != settings.single_user_id
                or not settings.shared_pin
                or not hmac.compare_digest(
                    pin.encode(), settings.shared_pin.get_secret_value().encode()
                )
            ):
                raise HTTPException(401, "Invalid user or PIN")
        result = agent.request(
            "POST",
            "/api/companion/unlock",
            json={
                "user_id": body.user_id,
                "pin": None if settings.single_user_id else pin,
                "lifetime_seconds": 86400,
            },
        ).json()
        with station.lock:
            superseded = generation != station.generation
            previous = station.remote_token
            if not superseded:
                station.browser_token, station.remote_token = (
                    secrets.token_urlsafe(32),
                    result["session_token"],
                )
                station.operator = None
                station.last_activity = time.monotonic()
                response.set_cookie(
                    COOKIE,
                    station.browser_token,
                    httponly=True,
                    samesite="none"
                    if settings.frame_ancestors and settings.public_url.startswith("https:")
                    else "strict",
                    secure=settings.public_url.startswith("https:"),
                    path="/",
                    max_age=86400,
                )
        if superseded:
            agent.revoke_session(result["session_token"])
            raise HTTPException(409, "Station changed; unlock again")
        if previous:
            agent.revoke_session(previous)
        return {"ok": True}

    @app.post("/api/station/printers", status_code=201)
    def add_printer(body: LocalPrinter, request: Request) -> dict[str, bool]:
        csrf(request)
        token = current(request, touch=True)
        if not agent.online:
            raise HTTPException(503, "The main server is unavailable")
        try:
            agent.add_printer(body, token)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"ok": True}

    @app.put("/api/station/printers/{local_id}/enabled")
    def enable_printer(local_id: str, body: PrinterEnabled, request: Request) -> dict[str, bool]:
        csrf(request)
        token = current(request, touch=True)
        if not agent.online:
            raise HTTPException(503, "The main server is unavailable")
        try:
            agent.enable_printer(local_id, body.enabled, token)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"ok": True}

    @app.post("/api/station/lock")
    def lock(request: Request, response: Response) -> dict[str, bool]:
        csrf(request)
        try:
            token = current(request)
        except HTTPException:
            with station.lock:
                if station.browser_token:
                    raise
                station.clear()
            return {"ok": True}
        with station.lock:
            if token != station.remote_token:
                raise HTTPException(409, "Station changed; refresh the dashboard")
            station.clear()
        response.delete_cookie(COOKIE, path="/")
        agent.revoke_session(token)
        return {"ok": True}

    @app.post("/api/station/activity")
    def activity(request: Request) -> dict[str, bool | int]:
        csrf(request)
        current(request, touch=True)
        return {"ok": True, "lock_remaining_seconds": settings.lock_timeout_seconds}

    @app.post("/api/station/printers/{local_id}/stop")
    def local_stop(local_id: str, body: Stop, request: Request) -> dict[str, bool]:
        csrf(request)
        executor = agent.executors.get(local_id)
        if not executor:
            raise HTTPException(404, "Local printer not found")
        if not isinstance(executor.backend, ControlledPrinterBackend):
            raise HTTPException(409, "This printer does not support stopping a running batch")
        mode: StopMode = body.mode
        token = None
        try:
            token = current(request, touch=True)
        except HTTPException:
            pass
        offline_allowed = (
            settings.allow_offline_emergency_stop
            if mode == "emergency"
            else settings.allow_offline_stop_after_label
        )
        locked_allowed = (
            settings.allow_locked_emergency_stop
            if mode == "emergency"
            else settings.allow_locked_stop_after_label
        )
        if not agent.online:
            if not offline_allowed or not token and not locked_allowed:
                raise HTTPException(403, "This local stop is disabled while offline or locked")
        elif token:
            identifier = agent.identifiers.get(local_id)
            agent.request(
                "POST", f"/api/printers/{identifier}/stop", token=token, json={"mode": mode}
            )
        elif not locked_allowed:
            raise HTTPException(403, "This local stop is disabled while locked")
        identifier = agent.identifiers.get(local_id)
        if not identifier:
            raise HTTPException(409, "Printer has not registered with the main server")
        journal.record_stop(
            identifier,
            mode,
            (station.operator or {}).get("id") if token else None,
            offline=not agent.online,
            locked=token is None,
        )
        executor.control.request(mode)
        return {"ok": True}

    @app.api_route("/api/proxy/{path:path}", methods=["GET", "POST", "PUT"])
    async def proxy(path: str, request: Request) -> Response:
        if not (
            PROXY_PATH.fullmatch(path) or request.method == "GET" and PACKING_PATH.fullmatch(path)
        ):
            raise HTTPException(403, "This operation is not available through the station")
        if request.method != "GET":
            csrf(request)
        token = current(request, touch=request.method != "GET")
        if not agent.online:
            raise HTTPException(503, "The main server is unavailable")
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 1_000_000:
                raise HTTPException(413, "Request is too large")
        from starlette.concurrency import run_in_threadpool

        forwarded = {"Content-Type": "application/json"}
        if confirmation := request.headers.get("x-tape-shortage-confirmation"):
            forwarded["X-Tape-Shortage-Confirmation"] = confirmation
        result = await run_in_threadpool(
            agent.request,
            request.method,
            "/api/" + path,
            token=token,
            params=list(request.query_params.multi_items()),
            content=bytes(content),
            headers=forwarded,
        )
        return Response(
            result.content,
            status_code=result.status_code,
            media_type=result.headers.get("content-type", "application/json"),
            headers={"Cache-Control": "private, no-store"},
        )

    if (assets / "assets").exists():
        app.mount("/assets", StaticFiles(directory=assets / "assets"), name="assets")
    fonts = Path(__file__).resolve().parent.parent / "app" / "fonts"
    app.mount("/fonts", StaticFiles(directory=fonts), name="fonts")

    @app.get("/")
    def root() -> FileResponse:
        if not (assets / "companion.html").exists():
            raise HTTPException(503, "Build the companion web interface first")
        return FileResponse(assets / "companion.html")

    app.add_middleware(HttpSecurity, allowed_frames=settings.frame_ancestors)
    return app
