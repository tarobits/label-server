"""Independent device workers with one short-lived database reservation lock."""

import logging
from collections.abc import Callable
from dataclasses import replace
from threading import Event, Lock, Thread
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.destinations import (
    automatic_printing_disabled,
    busy,
    installed_profile,
    members,
    printer_state,
)
from app.font_assets import FontStore
from app.image_assets import ImageStore
from app.models import (
    Batch,
    Cartridge,
    CompanionPrinter,
    LabelCopy,
    PrinterDevice,
    PrintJob,
    PrintRun,
    State,
    TapeProfile,
)
from app.printer.base import DurablePrinterBackend, PrinterBackend
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
            check_prices=self.check_prices,
            supports_job=lambda job: self.supports_media(job, definition.id),
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
                if not isinstance(backend, DurablePrinterBackend) or not backend.has_batch(
                    batch.id
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
                    backend = self.backends.get(device.id, backend)
                    if session.get(CompanionPrinter, device.id):
                        from app.printer.remote import RemotePrinterBackend

                        backend = RemotePrinterBackend(self.factory, device.id, backend)
                    self._add(
                        replace(definition, id=device.id, name=device.name),
                        backend,
                    )

    def retire(self, identifier: str) -> None:
        # Caller holds both the fleet and hardware locks through commit.
        worker = self.workers.pop(identifier, None)
        if worker:
            worker.retired = True
        self.configuration_errors.pop(identifier, None)
        self.registry.unregister(identifier)

    def reconfigure(self, device: PrinterDevice) -> None:
        # Caller holds the fleet lock and this worker's hardware lock through commit.
        definition, backend = self.backend_factory(device.driver, device.config)
        backend = self.backends.get(device.id, backend)
        with self.factory() as session:
            if session.get(CompanionPrinter, device.id):
                from app.printer.remote import RemotePrinterBackend

                backend = RemotePrinterBackend(self.factory, device.id, backend)
        self.configuration_errors.pop(device.id, None)
        if device.id not in self.workers:
            self._add(
                replace(definition, id=device.id, name=device.name),
                backend,
            )
            return
        worker = self.workers[device.id]
        worker.backend = backend
        from app.printer.base import PrinterStatus

        worker.latest_status = PrinterStatus(False, None)
        self.registry.replace(replace(definition, id=device.id, name=device.name), worker.backend)

    def check_prices(self, session: Session, printer_id: str) -> None:
        """Evaluate inventory independently of installed media, holds and thresholds."""
        from app.job_access import job_eligible
        from app.pricing import check_affordable_inventory

        for job in session.scalars(
            select(PrintJob).join(LabelCopy).where(LabelCopy.state == State.QUEUED).distinct()
        ):
            if not job.template_snapshot.get("pricing", {}).get("maximum") or not job_eligible(
                session, job
            ):
                continue
            candidates = [
                identifier
                for identifier in self._candidates(session, job)
                if identifier in self.workers and self.supports_geometry(job, identifier)
            ]
            # One member owns this calculation, but prices consider all compatible
            # members. A cheaper group member must not produce alternating alerts.
            if candidates and candidates[0] == printer_id:
                check_affordable_inventory(
                    session, job, [self.workers[identifier].backend for identifier in candidates]
                )

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
        from app.migration_gate import migration_pending

        if migration_pending(session):
            return None

        if self.enforce_job_access and not job_eligible(session, job):
            return None

        candidates = self._candidates(session, job)
        if required_printer is not None:
            candidates = [identifier for identifier in candidates if identifier == required_printer]
        for identifier in candidates:
            if self._printer_blocker(session, job, identifier, manual, require_ready) is None:
                return identifier
        return None

    def _candidates(self, session: Session, job: PrintJob) -> list[str]:
        candidates = members(session, job.destination_id)
        retry = job.template_snapshot.get("retry")
        if retry:
            return [retry["printer_id"]] if retry["printer_id"] in candidates else []
        run = session.get(PrintRun, job.run_id) if job.run_id else None
        if run and run.assigned_printer_id:
            return [run.assigned_printer_id] if run.assigned_printer_id in candidates else []
        return candidates

    def _printer_blocker(
        self,
        session: Session,
        job: PrintJob,
        identifier: str,
        manual: bool,
        require_ready: bool,
    ) -> str | None:
        """Use the same eligibility checks for routing and explanations."""
        worker = self.workers.get(identifier)
        state = printer_state(session, identifier)
        if not worker:
            if identifier in self.configuration_errors:
                return "is unavailable because its printer configuration could not be loaded"
            return "is unavailable because its printer worker is not running"
        if busy(session, identifier):
            printing = session.scalar(
                select(Batch.id)
                .where(Batch.printer_id == identifier, Batch.state == State.PRINTING)
                .limit(1)
            )
            if printing:
                return "is currently printing. Wait for its current batch to finish"
            return "has a batch awaiting review. Review that batch before printing again"
        if not manual and automatic_printing_disabled(session, identifier):
            return "requires manual printing"
        if state.automatic_printing_held and not manual:
            return "has automatic printing paused"
        cartridge = (
            session.get(Cartridge, state.active_cartridge_id) if state.active_cartridge_id else None
        )
        if self.enforce_job_access and cartridge is not None:
            from app.cartridge_access import can_use_cartridge
            from app.use_overrides import pending_authorization

            if not can_use_cartridge(session, job, cartridge) and not pending_authorization(
                session, job, cartridge
            ):
                from app.access import access_context

                request = session.info.get("request")
                if not (
                    manual
                    and request
                    and access_context(request).can_cartridge(cartridge.id, "approve_use")
                ):
                    return "has a cartridge the requester may not use"
            from app.pricing import affordable

            if not affordable(session, job, cartridge, worker.backend):
                return "has a cartridge above the requester's remaining maximum"
        if not manual and cartridge is not None and cartridge.remaining_mm <= 0:
            return "has no tape remaining"
        if installed_profile(session, identifier) != job.profile_id:
            return "does not have a cartridge matching the required tape profile installed"
        status = worker.latest_status
        if require_ready:
            if not status.connected:
                return "is offline. Reconnect it before printing"
            if status.error:
                return f"reports an error: {status.error}"
            if status.tape_width_mm != job.width_mm:
                detected = (
                    f"{status.tape_width_mm:g} mm tape"
                    if status.tape_width_mm is not None
                    else "no tape width"
                )
                return f"detects {detected}, but these labels require {job.width_mm:g} mm tape"
        if not self.supports_geometry(job, identifier):
            return "does not support these labels' media, saved resolution or printable area"
        return None

    def supports_media(self, job: PrintJob, identifier: str) -> bool:
        caps = self.registry.definition(identifier).capabilities
        from app.media import MediaProperties, require_supported_media

        try:
            media = MediaProperties.model_validate(
                job.template_snapshot.get("document", {}).get("media", {})
            )
            require_supported_media(
                media,
                job.width_mm,
                media_family=caps.media_family,
                media_kind=caps.media_kind.value,
                supported_widths_mm=caps.supported_widths_mm,
                fixed_label_sizes_mm=caps.fixed_label_sizes_mm,
            )
            if media.label_length_mm is not None and job.length_mm != media.label_length_mm:
                return False
        except ValueError:
            return False
        return True

    def supports_geometry(self, job: PrintJob, identifier: str) -> bool:
        # Group routing must preserve the frozen printable geometry and resolution.
        if not self.supports_media(job, identifier):
            return False
        spec = job.template_snapshot.get("render_spec", {})
        caps = self.registry.definition(identifier).capabilities
        resolution = (spec.get("dpi_x") or spec.get("dpi", 180), spec.get("dpi", 180))
        modes = set((caps.resolution_modes or {}).values()) | {(caps.dpi_x, caps.dpi_y)}
        return not (
            resolution not in modes
            or (spec.get("printable_widths_mm") or {}).get(
                f"{job.template_snapshot.get('document', {}).get('width_mm', job.width_mm):g}"
            )
            != (caps.printable_widths_mm or {}).get(f"{job.width_mm:g}")
            or spec.get("margin_mm", 1) != caps.printable_margin_mm
        )

    def manual_print_blocker(self, session: Session, job: PrintJob) -> str:
        """Explain a rejected manual route without contacting a busy printer."""
        from app.job_access import job_eligible

        if self.enforce_job_access and not job_eligible(session, job):
            return (
                "Printing is blocked by an access or content hold. An administrator must review it"
            )
        candidates = self._candidates(session, job)
        run = session.get(PrintRun, job.run_id) if job.run_id else None
        assigned = (
            session.get(PrinterDevice, run.assigned_printer_id)
            if run and run.assigned_printer_id
            else None
        )
        prefix = f'This run is assigned to "{assigned.name}". ' if assigned else ""
        if not candidates:
            return prefix + "No eligible printer remains in the selected destination"
        profile = session.get(TapeProfile, job.profile_id)
        required = f'"{profile.name}" ({job.width_mm:g} mm)' if profile else f"{job.width_mm:g} mm"
        matching = [
            identifier
            for identifier in candidates
            if installed_profile(session, identifier) == job.profile_id
        ]
        if not matching:
            names = ", ".join(
                f'"{device.name}"'
                for identifier in candidates
                if (device := session.get(PrinterDevice, identifier))
            )
            subject = (
                "The assigned printer" if assigned else "No printer in the selected destination"
            )
            verb = "does not have" if assigned else "has"
            return (
                prefix
                + f"{subject} ({names}) {verb} a cartridge matching tape profile {required} installed"
            )
        reasons = []
        for identifier in matching:
            device = session.get(PrinterDevice, identifier)
            reason = self._printer_blocker(
                session, job, identifier, manual=True, require_ready=True
            )
            if reason:
                reasons.append(f'"{device.name if device else identifier}" {reason}')
        return prefix + f"For tape profile {required}: " + "; ".join(reasons)

    def _run(self, worker: QueueWorker) -> None:
        while not self.stop.is_set() and not worker.retired:
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
