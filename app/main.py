import fcntl
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url

from app.access import LocalOwnerPolicy, authorize_request
from app.api import router
from app.config import Settings
from app.db import make_engine, session_factory
from app.font_assets import FontStore
from app.identity import LOCAL_OWNER_ID
from app.image_assets import ImageStore
from app.models import PrinterState
from app.notifications import NtfySender, RoutedNotificationSender, deliver_pending
from app.printer.base import PrinterBackend
from app.printer.factory import configured_printer
from app.printer.registry import PrinterRegistry
from app.queue import QueueWorker
from app.render import FONT_DIR
from app.templates import seed_templates

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    backend: PrinterBackend | None = None,
    start_worker: bool = True,
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
    definition, configured_backend = configured_printer(settings)
    worker = QueueWorker(factory, backend or configured_backend, fonts, images)
    registry = PrinterRegistry()
    registry.register(definition, worker.backend)
    stop, wake = Event(), Event()

    def run_queue() -> None:
        while not stop.is_set():
            wake.clear()
            try:
                worker.tick()
            except Exception:
                logger.exception("Queue tick failed; durable state will be retried")
                try:
                    worker.recover()
                except Exception:
                    logger.exception("Could not reconcile interrupted print attempts")
            wake.wait(settings.worker_interval_seconds)

    def run_notifications() -> None:
        import time

        sender = RoutedNotificationSender({LOCAL_OWNER_ID: NtfySender(settings)})
        while not stop.is_set():
            try:
                deliver_pending(factory, sender, time.time())
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
                if session.get(PrinterState, 1) is None:
                    session.add(PrinterState(id=1))
                seed_templates(session)
            worker.recover()
            if start_worker:
                threads.append(Thread(target=run_queue, name="printer-worker", daemon=True))
                if settings.ntfy_url:
                    threads.append(
                        Thread(target=run_notifications, name="notification-worker", daemon=True)
                    )
                for thread in threads:
                    thread.start()
            yield
        finally:
            stop.set()
            wake.set()
            for thread in threads:
                thread.join()
            engine.dispose()
            lock_file.close()

    app = FastAPI(title="Label Printer Server", version="0.1.0", lifespan=lifespan)
    app.state.access_policy = LocalOwnerPolicy()
    app.state.fonts = fonts
    app.state.images = images
    app.state.registry = registry
    app.state.settings = settings
    app.state.factory = factory
    app.state.worker = worker
    app.state.engine = engine
    app.state.wake = wake
    from app.font_api import router as font_router
    from app.image_api import router as image_router
    from app.runs import router as runs_router

    app.include_router(router, dependencies=[Depends(authorize_request)])
    app.include_router(runs_router, dependencies=[Depends(authorize_request)])
    app.include_router(font_router, dependencies=[Depends(authorize_request)])
    app.include_router(image_router, dependencies=[Depends(authorize_request)])
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
                "stage": "Backend foundation; mock printer and renderer",
                "api_docs": "/docs",
                "frontend": "Run npm install and npm run build in frontend/, or use the Vite dev server",
            }
        )

    return app
