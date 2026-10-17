"""Independent device workers with one short-lived database reservation lock."""

import logging
from collections.abc import Callable
from dataclasses import replace
from threading import Event, Lock, Thread
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.destinations import busy, installed_profile, members, printer_state
from app.font_assets import FontStore
from app.image_assets import ImageStore
from app.models import Cartridge, PrinterDevice, PrintJob
from app.printer.base import PrinterBackend
from app.printer.factory import configured_printer
from app.printer.registry import PrinterDefinition, PrinterRegistry
from app.queue import QueueWorker

logger = logging.getLogger(__name__)


class PrinterFleet:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        fonts: FontStore,
        images: ImageStore,
        registry: PrinterRegistry,
        backends: dict[str, PrinterBackend] | None = None,
        backend_factory: Callable[
            [str, dict[str, Any]], tuple[PrinterDefinition, PrinterBackend]
        ] = configured_printer,
    ) -> None:
        self.factory, self.settings = factory, settings
        self.fonts, self.images, self.registry = fonts, images, registry
        self.lock = Lock()
        self.stop, self.wake = Event(), Event()
        self.workers: dict[str, QueueWorker] = {}
        self.configuration_errors: dict[str, str] = {}
        self.threads: list[Thread] = []
        self.running = False
        self.enforce_job_access = True
        self.backends = backends or {}
        self.backend_factory = backend_factory

    def _add(self, definition: PrinterDefinition, backend: PrinterBackend) -> None:
        worker = QueueWorker(
            self.factory,
            backend,
            self.fonts,
            self.images,
            printer_id=definition.id,
            lock=self.lock,
            choose=self.choose,
            enforce_job_access=self.enforce_job_access,
        )
        self.registry.register(definition, backend)
        self.workers[definition.id] = worker
        # Also reconcile a previously unavailable registration when repaired at runtime.
        with self.factory.begin() as session:
            from app.models import Batch, State

            for batch in session.scalars(
                select(Batch).where(
                    Batch.printer_id == definition.id, Batch.state == State.PRINTING
                )
            ):
                worker._uncertain(session, batch, 0, "Server restarted during printing")
        if self.running:
            self._start(worker)

    def sync(self) -> None:
        with self.lock, self.factory() as session:
            for device in session.scalars(select(PrinterDevice)):
                if device.id not in self.workers and not device.config.get("retired"):
                    try:
                        definition, backend = self.backend_factory(device.driver, device.config)
                    except ValueError as error:
                        self.configuration_errors[device.id] = str(error)
                        continue
                    self.configuration_errors.pop(device.id, None)
                    self._add(
                        replace(definition, id=device.id, name=device.name),
                        self.backends.get(device.id, backend),
                    )

    def reconfigure(self, device: PrinterDevice) -> None:
        # Caller holds the fleet lock and this worker's hardware lock through commit.
        definition, backend = self.backend_factory(device.driver, device.config)
        self.configuration_errors.pop(device.id, None)
        if device.id not in self.workers:
            self._add(
                replace(definition, id=device.id, name=device.name),
                self.backends.get(device.id, backend),
            )
            return
        worker = self.workers[device.id]
        worker.backend = self.backends.get(device.id, backend)
        from app.printer.base import PrinterStatus

        worker.latest_status = PrinterStatus(False, None)
        self.registry.replace(replace(definition, id=device.id, name=device.name), worker.backend)

    def choose(
        self,
        session: Session,
        job: PrintJob,
        manual: bool = False,
        required_printer: str | None = None,
        *,
        require_ready: bool = True,
    ) -> str | None:
        from app.job_access import job_eligible
        from app.models import PrintRun

        if self.enforce_job_access and not job_eligible(session, job):
            return None

        run = session.get(PrintRun, job.run_id) if job.run_id else None
        candidates = members(session, job.destination_id)
        if run and run.assigned_printer_id:
            candidates = [run.assigned_printer_id] if run.assigned_printer_id in candidates else []
        if required_printer is not None:
            candidates = [identifier for identifier in candidates if identifier == required_printer]
        for identifier in candidates:
            worker = self.workers.get(identifier)
            state = printer_state(session, identifier)
            if (
                not worker
                or busy(session, identifier)
                or (state.automatic_printing_held and not manual)
            ):
                continue
            cartridge = (
                session.get(Cartridge, state.active_cartridge_id)
                if state.active_cartridge_id
                else None
            )
            if not manual and cartridge is not None and cartridge.remaining_mm <= 0:
                continue
            status = worker.latest_status
            if (
                installed_profile(session, identifier) != job.profile_id
                or require_ready
                and (not status.connected or status.error or status.tape_width_mm != job.width_mm)
            ):
                continue
            # Group routing must preserve the frozen printable geometry and resolution.
            spec = job.template_snapshot.get("render_spec", {})
            caps = self.registry.definition(identifier).capabilities
            resolution = (spec.get("dpi_x") or spec.get("dpi", 180), spec.get("dpi", 180))
            modes = set((caps.resolution_modes or {}).values()) | {(caps.dpi_x, caps.dpi_y)}
            if (
                resolution not in modes
                or (spec.get("printable_widths_mm") or {}).get(
                    f"{job.template_snapshot.get('document', {}).get('width_mm', job.width_mm):g}"
                )
                != (caps.printable_widths_mm or {}).get(f"{job.width_mm:g}")
                or spec.get("margin_mm", 1) != caps.printable_margin_mm
            ):
                continue
            return identifier
        return None

    def _run(self, worker: QueueWorker) -> None:
        while not self.stop.is_set():
            self.wake.clear()
            try:
                worker.tick()
            except Exception:
                logger.exception("Printer %s tick failed", worker.printer_id)
                try:
                    worker.recover()
                except Exception:
                    logger.exception("Could not reconcile printer %s", worker.printer_id)
            self.wake.wait(self.settings.worker_interval_seconds)

    def _start(self, worker: QueueWorker) -> None:
        thread = Thread(
            target=self._run, args=(worker,), name=f"printer-{worker.printer_id}", daemon=True
        )
        self.threads.append(thread)
        thread.start()

    def start(self) -> None:
        self.running = True
        for worker in self.workers.values():
            self._start(worker)

    def close(self) -> None:
        self.stop.set()
        self.wake.set()
        for thread in self.threads:
            thread.join()
