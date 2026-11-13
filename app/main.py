import fcntl
import logging
from collections.abc import Awaitable, Callable
from contextlib import ExitStack, asynccontextmanager
from threading import Lock, Thread
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router
from app.assets.font_assets import FontStore
from app.assets.image_assets import ImageStore
from app.authn.access import authorize_request
from app.authn.auth import AuthRateLimiter, initialize_auth, session_user
from app.config import Settings
from app.database_lock import database_owner
from app.db import make_engine, session_factory
from app.i18n import Message, request_language, validation_details
from app.maintenance.deletion import is_deleted, purge_expired
from app.maintenance.releases import ReleaseChecker
from app.notifications.notification_routing import deliver_routed_pending
from app.printer.base import PrinterBackend
from app.printer.factory import configured_printer
from app.printer.registry import PrinterDefinition, PrinterRegistry
from app.printing.fleet import PrinterFleet
from app.render import FONT_DIR
from app.templates.template_previews import TemplatePreviews
from app.templates.templates import seed_templates

logger = logging.getLogger(__name__)
# Checked by the updater before relying on the startup/HTTP validation gate.
UPDATE_VALIDATION_PROTOCOL = 1


def create_app(
    settings: Settings | None = None,
    backends: dict[str, PrinterBackend] | None = None,
    start_worker: bool = True,
    backend_factory: Callable[
        [str, dict[str, Any]], tuple[PrinterDefinition, PrinterBackend]
    ] = configured_printer,
) -> FastAPI:
    from app.deployment import require_role

    require_role("main")
    settings = settings or Settings()
    from app.logging_config import configure_logging

    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    settings.state_directory.mkdir(parents=True, exist_ok=True)
    fonts = FontStore(settings.state_directory / "cache" / "assets" / "fonts", factory)
    images = ImageStore(fonts.root.parent / "images", factory)

    def asset_deleted(kind: str, identifier: str) -> bool:
        with factory() as session:
            return is_deleted(session, kind, identifier)

    fonts.unavailable = lambda identifier: asset_deleted("fonts", identifier)
    images.unavailable = lambda identifier: asset_deleted("images", identifier)
    registry = PrinterRegistry()
    fleet = PrinterFleet(factory, settings, fonts, images, registry, backends, backend_factory)
    stop, wake = fleet.stop, fleet.wake
    update_marker = settings.state_directory / ".update-in-progress"
    activation_lock = Lock()

    def run_notifications() -> None:
        import time

        next_cleanup = 0.0
        next_cache_cleanup = 0.0
        while not stop.is_set():
            try:
                from app.assets.asset_cache import expire
                from app.printing.request_notifications import schedule_request_digest

                if time.time() >= next_cache_cleanup:
                    expire(
                        settings.state_directory / "cache" / "assets",
                        settings.asset_cache_idle_seconds,
                    )
                    next_cache_cleanup = time.time() + min(60, settings.asset_cache_idle_seconds)

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
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        if engine.dialect.name == "sqlite" and engine.url.database in (None, "", ":memory:"):
            raise RuntimeError("Use a file-backed SQLite database")
        lock_file = settings.worker_lock_path.open("a")
        ownership = ExitStack()
        threads: list[Thread] = []
        try:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "Another server owns this database; run exactly one process"
                ) from error

            def lost_ownership() -> None:
                stop.set()
                wake.set()
                for worker in tuple(fleet.workers.values()):
                    worker.control.request("after_current")

            ownership.enter_context(database_owner(engine, enforce=True, on_loss=lost_ownership))
            from app.maintenance.relationship_migration import pending as relationships_pending
            from migrations.relationships_v1 import VERSION as RELATIONSHIP_VERSION
            from migrations.relationships_v1 import finalize

            with factory() as session:
                from app.models import ReleaseMigration

                migration = session.get(ReleaseMigration, RELATIONSHIP_VERSION)
                ready = bool(
                    migration and migration.completed_at is None and migration.draft.get("ready")
                )
            if ready:
                try:
                    with engine.connect() as connection:
                        finalize(connection)
                    # Do not reuse connections with a pre-rebuild SQLite schema cache.
                    engine.dispose()
                except Exception:
                    logger.exception(
                        "Relationship constraints could not be applied; keeping migration mode"
                    )
            with factory() as session:
                app.state.relationship_maintenance = relationships_pending(session)
            if app.state.relationship_maintenance:
                initialize_auth(factory, settings.state_directory)
                # No asset purge, recovery, notification delivery, printer polling,
                # or dispatch may observe an administrator's partially repaired graph.
                yield
                return
            with factory.begin() as session:
                import time

                from app.assets.asset_cache import expire
                from app.assets.asset_import import archive_legacy_assets, import_assets

                import_assets(session, settings.state_directory / "assets")
                purge_expired(session, fonts, images, time.time())
                seed_templates(session)
            archived_assets = archive_legacy_assets(factory, settings.state_directory / "assets")
            if archived_assets:
                logger.info("Legacy asset files archived to %s", archived_assets)
            expire(settings.state_directory / "cache" / "assets", settings.asset_cache_idle_seconds)
            initialize_auth(factory, settings.state_directory)
            fleet.enforce_job_access = app.state.access_policy is None
            if fleet.enforce_job_access:
                from app.printing.job_access import reconcile_access_holds

                with factory.begin() as session:
                    reconcile_access_holds(session)
            fleet.sync()
            for device in fleet.workers.values():
                device.recover()

            def activate() -> None:
                # The updater validates startup before allowing external effects.
                while update_marker.exists():
                    if stop.wait(0.25):
                        return
                with activation_lock:
                    if stop.is_set():
                        return
                    fleet.start()
                    notifications = Thread(
                        target=run_notifications, name="notification-worker", daemon=True
                    )
                    threads.append(notifications)
                    notifications.start()

            if start_worker and update_marker.exists():
                starter = Thread(target=activate, name="update-validation", daemon=True)
                threads.append(starter)
                starter.start()
            elif start_worker:
                activate()
            yield
        finally:
            with activation_lock:
                fleet.close()
            for thread in threads:
                thread.join()
            ownership.close()
            engine.dispose()
            lock_file.close()

    app = FastAPI(title="Taro's Label Room", version=__version__, lifespan=lifespan)
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from app.i18n import http_error

    app.add_exception_handler(StarletteHTTPException, http_error)
    from app.http_security import HttpSecurity

    app.state.relationship_maintenance = False
    from app.maintenance.relationship_migration import router as relationship_router

    app.include_router(relationship_router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> Response:
        sensitive = request.url.path.startswith(
            ("/api/auth/", "/api/companion/", "/api/companions/", "/api/admin/", "/api/migration/")
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": jsonable_encoder(
                    validation_details(
                        error.errors(), request_language(request), sensitive=sensitive
                    )
                )
            },
        )

    releases = ReleaseChecker(settings)
    app.state.releases = releases
    app.state.access_policy = None
    app.state.auth_limiter = AuthRateLimiter()
    app.state.fonts = fonts
    app.state.images = images
    app.state.template_previews = TemplatePreviews(fonts.root.parent / "template-previews")
    app.state.registry = registry
    app.state.settings = settings
    app.state.factory = factory
    app.state.fleet = fleet
    app.state.engine = engine
    app.state.wake = wake
    from app.accounts.accounting_api import router as accounting_router
    from app.accounts.billing_api import router as billing_router
    from app.assets.font_api import router as font_router
    from app.assets.image_api import router as image_router
    from app.audit.audit_api import router as audit_router
    from app.authn.admin_api import router as admin_router
    from app.authn.auth_api import router as auth_router
    from app.authn.avatar_api import router as avatar_router
    from app.authn.resource_api import router as resource_router
    from app.companion.companion_api import router as companion_router
    from app.companion.companion_transport_api import router as companion_transport_router
    from app.maintenance.migration_api import router as migration_router
    from app.maintenance.recovery_api import router as recovery_router
    from app.notifications.inbox_api import router as inbox_router
    from app.notifications.notification_api import router as notification_endpoints_router
    from app.notifications.push_api import router as push_router
    from app.printing.batch_reviews import router as batch_reviews_router
    from app.printing.cartridge_quote_api import router as cartridge_quote_router
    from app.printing.fleet_api import router as fleet_router
    from app.printing.job_access_api import router as access_holds_router
    from app.printing.printer_lifecycle import router as printer_lifecycle_router
    from app.printing.queue_routing_api import router as queue_routing_router
    from app.printing.request_api import router as requests_router
    from app.printing.retry_api import router as retry_router
    from app.printing.runs import router as runs_router

    app.include_router(auth_router)
    app.include_router(avatar_router)
    app.include_router(audit_router)
    app.include_router(resource_router)
    app.include_router(migration_router)
    app.include_router(accounting_router)
    app.include_router(billing_router)
    app.include_router(retry_router)
    app.include_router(batch_reviews_router)
    app.include_router(cartridge_quote_router)
    app.include_router(companion_router)
    app.include_router(companion_transport_router)
    app.include_router(inbox_router)
    app.include_router(recovery_router)
    app.include_router(push_router)
    app.include_router(admin_router)
    app.include_router(notification_endpoints_router)
    app.include_router(router, dependencies=[Depends(authorize_request)])
    app.include_router(fleet_router, dependencies=[Depends(authorize_request)])
    app.include_router(printer_lifecycle_router, dependencies=[Depends(authorize_request)])
    app.include_router(queue_routing_router, dependencies=[Depends(authorize_request)])
    app.include_router(runs_router, dependencies=[Depends(authorize_request)])
    app.include_router(font_router, dependencies=[Depends(authorize_request)])
    app.include_router(image_router, dependencies=[Depends(authorize_request)])
    app.include_router(requests_router, dependencies=[Depends(authorize_request)])
    app.include_router(access_holds_router, dependencies=[Depends(authorize_request)])

    @app.middleware("http")
    async def private_api_responses(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if update_marker.exists() and request.url.path != "/api/health":
            return JSONResponse(
                status_code=503,
                content={"detail": "Update validation in progress"},
                headers={"Cache-Control": "no-store", "Retry-After": "1"},
            )
        if app.state.relationship_maintenance and request.url.path.startswith("/api/"):
            allowed = request.url.path in {
                "/api/health",
                "/api/version",
                "/api/auth/session",
                "/api/auth/login",
                "/api/auth/logout",
                "/api/auth/setup",
            } or request.url.path.startswith("/api/migration/relationships")
            if not allowed:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "An administrator must complete the relationship migration"},
                    headers={"Cache-Control": "no-store"},
                )
        try:
            response = await call_next(request)
        except Exception:
            from starlette.concurrency import run_in_threadpool

            from app.audit.action_failures import record_failed_action

            await run_in_threadpool(record_failed_action, request, 500)
            raise
        if response.status_code >= 400:
            from starlette.concurrency import run_in_threadpool

            from app.audit.action_failures import record_failed_action

            await run_in_threadpool(record_failed_action, request, response.status_code)
        if response.status_code < 400 and getattr(
            request.state, "authenticated_session_hash", None
        ):
            from starlette.concurrency import run_in_threadpool

            from app.authn.session_details import record_activity

            await run_in_threadpool(record_activity, request)
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
                raise HTTPException(401, Message("serverMessages.signInToViewVersionInformation"))
        return releases.status()

    app.mount("/fonts", StaticFiles(directory=FONT_DIR), name="fonts")
    if (settings.frontend_dist / "assets").is_dir():
        app.mount(
            "/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets"
        )

    @app.get("/favicon.ico", include_in_schema=False)
    @app.get("/favicon.svg", include_in_schema=False)
    @app.get("/apple-touch-icon.png", include_in_schema=False)
    @app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
    @app.get("/pwa-192x192.png", include_in_schema=False)
    @app.get("/pwa-512x512.png", include_in_schema=False)
    @app.get("/pwa-maskable-512x512.png", include_in_schema=False)
    def browser_icon(request: Request) -> FileResponse:
        icon = settings.frontend_dist / request.url.path.lstrip("/")
        if not icon.is_file():
            raise HTTPException(404, Message("serverMessages.iconNotFound"))
        return FileResponse(icon, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    @app.get("/sw.js", include_in_schema=False)
    def pwa_asset(request: Request) -> FileResponse:
        name = request.url.path.lstrip("/")
        asset = settings.frontend_dist / name
        if not asset.is_file():
            raise HTTPException(404, Message("serverMessages.appAssetNotFound"))
        media_type = (
            "application/manifest+json" if name == "manifest.webmanifest" else "text/javascript"
        )
        return FileResponse(
            asset,
            media_type=media_type,
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/", response_model=None)
    @app.get("/index.html", response_model=None, include_in_schema=False)
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

    app.add_middleware(
        HttpSecurity,
        json_limit=settings.json_body_limit_bytes,
        bulk_limit=settings.bulk_body_limit_bytes,
        expensive_limit=settings.expensive_request_limit,
    )
    return app
