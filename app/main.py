import fcntl
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url

from app import __version__
from app.access import authorize_request
from app.api import router
from app.auth import AuthRateLimiter, initialize_auth, session_user
from app.config import Settings
from app.db import make_engine, session_factory
from app.deletion import is_deleted, purge_expired
from app.fleet import PrinterFleet
from app.font_assets import FontStore
from app.image_assets import ImageStore
from app.notification_routing import deliver_routed_pending
from app.printer.base import PrinterBackend
from app.printer.factory import configured_printer
from app.printer.registry import PrinterDefinition, PrinterRegistry
from app.releases import ReleaseChecker
from app.render import FONT_DIR
from app.templates import seed_templates

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    backends: dict[str, PrinterBackend] | None = None,
    start_worker: bool = True,
    backend_factory: Callable[
        [str, dict[str, Any]], tuple[PrinterDefinition, PrinterBackend]
    ] = configured_printer,
) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    fonts = FontStore(
        Path(make_url(settings.database_url).database or "data/labels.db").resolve().parent
        / "assets"
        / "fonts"
    )
    images = ImageStore(fonts.root.parent / "images")

    def asset_deleted(kind: str, identifier: str) -> bool:
        with factory() as session:
            return is_deleted(session, kind, identifier)

    fonts.unavailable = lambda identifier: asset_deleted("fonts", identifier)
    images.unavailable = lambda identifier: asset_deleted("images", identifier)
    registry = PrinterRegistry()
    fleet = PrinterFleet(factory, settings, fonts, images, registry, backends, backend_factory)
    stop, wake = fleet.stop, fleet.wake

    def run_notifications() -> None:
        import time

        next_cleanup = 0.0
        while not stop.is_set():
            try:
                from app.request_notifications import schedule_request_digest

                with fleet.lock, factory.begin() as session:
                    if time.time() >= next_cleanup:
                        purge_expired(session, fonts, images, time.time())
                        next_cleanup = time.time() + 3600
                    schedule_request_digest(session, time.time())
                deliver_routed_pending(factory, settings, time.time())
            except Exception:
                logger.exception("Notification tick failed")
            stop.wait(settings.worker_interval_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        db_path = make_url(settings.database_url).database
        if not db_path or db_path == ":memory:":
            raise RuntimeError("Use a file-backed SQLite database")
        lock_file = Path(db_path).resolve().with_suffix(".worker.lock").open("a")
        threads: list[Thread] = []
        try:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "Another server owns this database; run exactly one process"
                ) from error
            with factory.begin() as session:
                import time

                purge_expired(session, fonts, images, time.time())
                seed_templates(session)
            initialize_auth(factory, Path(db_path).resolve().parent)
            fleet.enforce_job_access = app.state.access_policy is None
            if fleet.enforce_job_access:
                from app.job_access import reconcile_access_holds

                with factory.begin() as session:
                    reconcile_access_holds(session)
            fleet.sync()
            for device in fleet.workers.values():
                device.recover()
            if start_worker:
                fleet.start()
                threads.append(
                    Thread(target=run_notifications, name="notification-worker", daemon=True)
                )
                for thread in threads:
                    thread.start()
            yield
        finally:
            fleet.close()
            for thread in threads:
                thread.join()
            engine.dispose()
            lock_file.close()

    app = FastAPI(title="Label Printer Server", version=__version__, lifespan=lifespan)
    releases = ReleaseChecker(settings)
    app.state.releases = releases
    app.state.access_policy = None
    app.state.auth_limiter = AuthRateLimiter()
    app.state.fonts = fonts
    app.state.images = images
    app.state.registry = registry
    app.state.settings = settings
    app.state.factory = factory
    app.state.fleet = fleet
    app.state.engine = engine
    app.state.wake = wake
    from app.admin_api import router as admin_router
    from app.auth_api import router as auth_router
    from app.fleet_api import router as fleet_router
    from app.font_api import router as font_router
    from app.image_api import router as image_router
    from app.job_access_api import router as access_holds_router
    from app.notification_api import router as notification_endpoints_router
    from app.request_api import router as requests_router
    from app.runs import router as runs_router

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(notification_endpoints_router)
    app.include_router(router, dependencies=[Depends(authorize_request)])
    app.include_router(fleet_router, dependencies=[Depends(authorize_request)])
    app.include_router(runs_router, dependencies=[Depends(authorize_request)])
    app.include_router(font_router, dependencies=[Depends(authorize_request)])
    app.include_router(image_router, dependencies=[Depends(authorize_request)])
    app.include_router(requests_router, dependencies=[Depends(authorize_request)])
    app.include_router(access_holds_router, dependencies=[Depends(authorize_request)])

    @app.middleware("http")
    async def private_api_responses(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"healthy": True}

    @app.get("/api/version")
    def version(request: Request) -> dict[str, Any]:
        from fastapi import HTTPException

        with factory() as session:
            if session_user(request, session) is None:
                raise HTTPException(401, "Sign in to view version information")
        return releases.status()

    app.mount("/fonts", StaticFiles(directory=FONT_DIR), name="fonts")
    if (settings.frontend_dist / "assets").is_dir():
        app.mount(
            "/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets"
        )

    @app.get("/", response_model=None)
    def root() -> FileResponse | JSONResponse:
        index = settings.frontend_dist / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {
                "stage": "Configure printers through the web UI",
                "api_docs": "/docs",
                "frontend": "Run npm install and npm run build in frontend/, or use the Vite dev server",
            }
        )

    return app
