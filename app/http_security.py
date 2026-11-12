"""Byte budgets before parsing, bounded expensive requests and explicit framing."""

import asyncio
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def frame_origins(values: list[str]) -> list[str]:
    result = []
    for value in values:
        url = urlsplit(value)
        if (
            not value.isascii()
            or url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or any(c.isspace() for c in value)
            or any(c in value for c in "*;'\"\\")
        ):
            raise ValueError(
                "Frame origins must be exact HTTP(S) origins without paths or wildcards"
            )
        # Accessing port also rejects malformed ports.
        _ = url.port
        result.append(value.rstrip("/"))
    return sorted(set(result))


class HttpSecurity:
    def __init__(
        self,
        app: ASGIApp,
        *,
        json_limit: int = 16 << 20,
        bulk_limit: int = 64 << 20,
        expensive_limit: int = 2,
        allowed_frames: list[str] | None = None,
    ):
        self.app = app
        self.json_limit, self.bulk_limit = json_limit, bulk_limit
        self.slots = BoundedSemaphore(expensive_limit)
        self.in_flight: set[asyncio.Task[None]] = set()
        self.frames = frame_origins(allowed_frames or [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, method = scope["path"], scope["method"]
        disconnected = False

        async def secure_send(message: Message) -> None:
            if disconnected:
                return
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [
                    (k, v)
                    for k, v in headers
                    if k.lower()
                    not in (
                        b"x-frame-options",
                        b"x-content-type-options",
                    )
                ]
                headers.append(
                    (
                        b"content-security-policy",
                        (
                            "frame-ancestors 'self'"
                            + (" " + " ".join(self.frames) if self.frames else "")
                        ).encode("ascii"),
                    )
                )
                if not self.frames:
                    headers.append((b"x-frame-options", b"SAMEORIGIN"))
                headers.append((b"x-content-type-options", b"nosniff"))
                message = {**message, "headers": headers}
            await send(message)

        expensive = (
            method in ("POST", "PUT")
            and (
                path
                in (
                    "/api/preview",
                    "/api/jobs",
                    "/api/image-jobs",
                    "/api/image-jobs/preview",
                    "/api/requests",
                    "/api/runs/prepare",
                    "/api/csv/parse",
                    "/api/logic/inspect",
                    "/api/logic/compile",
                    "/api/image-assets",
                    "/api/font-assets",
                    "/api/auth/avatar",
                )
                or path == "/api/templates"
                or path.startswith("/api/templates/")
                or (path.startswith("/api/batches/") and path.endswith(("/review", "/misprints")))
            )
        ) or (method == "GET" and ("preview" in path or path.startswith("/api/font-assets/")))
        admitted = False
        try:
            limit = (
                self.bulk_limit
                if path.startswith(("/api/runs", "/api/csv", "/api/migration"))
                else self.json_limit
            )
            if path.startswith("/api/auth/") and "avatar" not in path:
                limit = min(limit, 16384)
            # Count actual ASGI bytes, including chunked bodies and requests with
            # missing/incorrect Content-Length. No parsing happens until accepted.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > limit:
                    await JSONResponse({"detail": "Request body is too large"}, status_code=413)(
                        scope, receive, secure_send
                    )
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            # Slow/incomplete uploads must not monopolize render slots. Bodies
            # have their own byte budget; admit only once the body is complete,
            # before parsing/decoding or acquiring workers/transactions.
            if expensive:
                admitted = self.slots.acquire(blocking=False)
                if not admitted:
                    await JSONResponse(
                        {"detail": "Rendering is busy; try again shortly"},
                        status_code=503,
                        headers={"Retry-After": "1"},
                    )(scope, receive, secure_send)
                    return
            payload = bytes(body)
            del body
            delivered = False

            async def replay() -> Message:
                nonlocal delivered
                if disconnected:
                    return {"type": "http.disconnect"}
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": payload, "more_body": False}
                return await receive()

            if admitted:
                # Raw asyncio cancellation can abandon an AnyIO sync worker.
                # Keep the admitted application task alive until its worker and
                # transaction cleanup finish; only that task releases the slot.
                async def run_admitted() -> None:
                    try:
                        await self.app(scope, replay, secure_send)
                    finally:
                        self.slots.release()

                task = asyncio.create_task(run_admitted())
                self.in_flight.add(task)
                admitted = False

                def finished(completed: asyncio.Task[None]) -> None:
                    self.in_flight.discard(completed)
                    if not completed.cancelled():
                        completed.exception()

                task.add_done_callback(finished)
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    disconnected = True
                    raise
            else:
                await self.app(scope, replay, secure_send)
        finally:
            if admitted:
                self.slots.release()
