"""Outbound synchronization; hardware workers continue independently of network loss."""

import json
import time
from dataclasses import asdict
from threading import Event, Lock, Thread
from typing import Any, Callable

import httpx

from app import __version__
from app.printer.base import ConfirmableMediaBackend, MediaSelection, PrinterBackend, PrinterStatus
from app.printer.factory import configured_printer
from app.printer.registry import PrinterDefinition
from companion.config import LocalPrinter, Settings
from companion.executor import Executor
from companion.journal import Journal


class Agent:
    def __init__(
        self,
        settings: Settings,
        journal: Journal,
        client: httpx.Client | None = None,
        backend_factory: Callable[
            [str, dict[str, Any]], tuple[PrinterDefinition, PrinterBackend]
        ] = configured_printer,
    ):
        self.settings, self.journal = settings, journal
        self.client = client or httpx.Client(
            base_url=settings.server_url, timeout=10, follow_redirects=False
        )
        self.key_headers = {
            "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
            "X-Companion-Version": __version__,
        }
        self.backend_factory = backend_factory
        self.executors: dict[str, Executor] = {}
        self.identifiers: dict[str, str] = {}
        self.statuses: dict[str, dict[str, Any]] = {}
        self.dashboards: dict[str, dict[str, Any]] = {}
        self.dashboard_received: dict[str, float] = {}
        self.server_blocked: dict[str, bool] = {}
        self.names: dict[str, str] = {}
        self.threads: dict[str, Thread] = {}
        self.configurations: dict[str, tuple[str, dict[str, Any]]] = {}
        self.last_contact = 0.0
        self.users: dict[str, Any] = {}
        self.stop = Event()
        self.lock = Lock()
        for device in settings.printers:
            journal.seed_printer(device.model_dump())
        for device in self.devices:
            self.prepare_device(device)

    @property
    def devices(self) -> list[LocalPrinter]:
        return [LocalPrinter.model_validate(value) for value in self.journal.printers()]

    def prepare_device(self, device: LocalPrinter) -> None:
        if device.local_id in self.executors:
            return
        configuration = device.configuration.model_dump()
        _, backend = self.backend_factory(device.driver, configuration)
        self.executors[device.local_id] = Executor(self.journal, device.local_id, backend)
        self.configurations[device.local_id] = (device.driver, configuration)

    def add_printer(self, device: LocalPrinter, token: str) -> None:
        with self.lock:
            if len(self.devices) >= 32:
                raise ValueError("A companion supports at most 32 printers")
            # Validate locally before registering; hardware is never opened here.
            self.backend_factory(device.driver, device.configuration.model_dump())
            response = self.request(
                "POST", "/api/companion/printers", token=token, json=device.model_dump()
            ).json()
            if not response["enabled"]:
                raise ValueError("Restore this printer from the removed printers list")
            self.journal.seed_printer(device.model_dump())
            self.prepare_device(device)
            self.identifiers[device.local_id] = response["printer_id"]

    def enable_printer(self, local_id: str, enabled: bool, token: str) -> None:
        with self.lock:
            device = next(
                (
                    LocalPrinter.model_validate(value)
                    for value in self.journal.printers(enabled=not enabled)
                    if value["local_id"] == local_id
                ),
                None,
            )
            if not device:
                raise ValueError("Printer is no longer in that state; refresh the dashboard")
            if enabled and len(self.devices) >= 32:
                raise ValueError("A companion supports at most 32 printers")
            registered = self.request(
                "POST", "/api/companion/printers", token=token, json=device.model_dump()
            ).json()
            self.request(
                "PUT",
                f"/api/companion/printers/{registered['printer_id']}/enabled",
                token=token,
                json={"enabled": enabled},
            )
            self.journal.set_printer_enabled(local_id, enabled)
            if enabled:
                self.prepare_device(device)
                self.identifiers[local_id] = registered["printer_id"]

    @property
    def online(self) -> bool:
        return self.last_contact > time.monotonic() - 20

    def request(
        self, method: str, path: str, *, token: str | None = None, **kwargs: Any
    ) -> httpx.Response:
        headers = {**self.key_headers, **kwargs.pop("headers", {})}
        if token:
            headers["X-Companion-Session"] = token
        response = self.client.request(method, path, headers=headers, **kwargs)
        if response.status_code < 500:
            self.last_contact = time.monotonic() if response.status_code != 401 else 0
        response.raise_for_status()
        return response

    def revoke_session(self, token: str) -> None:
        self.journal.revoke_session(token)
        self.flush_revocations()

    def flush_revocations(self) -> None:
        for token in self.journal.pending_revocations():
            try:
                self.request("POST", "/api/companion/sessions/revoke", token=token)
            except httpx.HTTPError:
                return
            self.journal.acknowledge_revocation(token)

    def sync(self) -> None:
        self.flush_revocations()
        with self.lock:
            self._sync()

    def _sync(self) -> None:
        self.users = self.request("GET", "/api/companion/users").json()
        self.journal.bind_station(self.users["id"])
        if self.settings.single_user_id != self.users.get("bound_user_id"):
            raise ValueError("Deployment user does not match the administrator's companion binding")
        for event in self.journal.pending_events():
            self.request("POST", "/api/companion/events/stop", json=event)
            self.journal.acknowledge_event(event["id"])
        for identifier, result in self.journal.pending_results():
            self.request(
                "POST", f"/api/companion/batches/{identifier}/result", json=result.model_dump()
            )
            self.journal.acknowledge(identifier)
        for device in self.devices:
            local_id = device.local_id
            # The main server may move this physical slot onto an existing printer.
            registered = self.request(
                "POST", "/api/companion/printers", json=device.model_dump()
            ).json()
            self.identifiers[local_id] = registered["printer_id"]
            if not registered["enabled"]:
                self.journal.set_printer_enabled(local_id, False)
                continue
            executor = self.executors[local_id]
            if executor.lock.acquire(blocking=False):
                try:
                    try:
                        status = executor.backend.get_status()
                    except Exception as error:
                        status = PrinterStatus(
                            False,
                            None,
                            "Could not read printer status",
                            error_requires_investigation=not isinstance(error, OSError),
                        )
                    self.statuses[local_id] = asdict(status)
                finally:
                    executor.lock.release()
            status_data = self.statuses.get(local_id, asdict(PrinterStatus(False, None)))
            # Persistent local uncertainty is independent of a ready hardware status.
            status_data = {
                **status_data,
                "local_blocked": self.journal.blocked(local_id),
                "clearance_seen": self.journal.clearance(local_id),
            }
            response = self.request(
                "PUT",
                f"/api/companion/printers/{self.identifiers[local_id]}/status",
                json=status_data,
            ).json()
            if not response["enabled"]:
                self.journal.set_printer_enabled(local_id, False)
                continue
            self.server_blocked[local_id] = response["blocked"]
            self.dashboards[local_id] = response.get("dashboard", {})
            self.dashboard_received[local_id] = time.monotonic()
            self.names[local_id] = response["name"] or device.name
            saved_device = {
                "local_id": local_id,
                "name": self.names[local_id],
                "driver": response["driver"],
                "configuration": response["configuration"],
            }
            if device.model_dump() != saved_device:
                self.journal.update_printer(saved_device)
            try:
                self.journal.clear(local_id, response["clearance"])
            except ValueError:
                pass  # Results must be acknowledged before applying a human clearance.
            if executor.lock.acquire(blocking=False):
                try:
                    desired = (response["driver"], response["configuration"])
                    if desired != self.configurations[local_id]:
                        _, executor.backend = self.backend_factory(*desired)
                        self.configurations[local_id] = desired
                    if isinstance(executor.backend, ConfirmableMediaBackend):
                        selection = response.get("media_selection")
                        executor.backend.configure_media(
                            MediaSelection(**selection) if selection else None
                        )
                finally:
                    executor.lock.release()
        work = self.request("GET", "/api/companion/work").json()
        enabled_ids = {device.local_id for device in self.devices}
        for transfer in work:
            envelope = self.journal.receive(transfer["payload"], transfer["digest"])
            local_id = envelope.local_id
            if local_id not in enabled_ids:
                continue
            if self.identifiers.get(local_id) != envelope.printer_id:
                raise ValueError("Remote work belongs to an unknown printer")
            executor = self.executors[local_id]
            if transfer.get("stop_mode"):
                executor.control.request(transfer["stop_mode"])
            if self.journal.row(envelope.batch_id)["phase"] not in ("prepared", "authorized"):
                continue
            if local_id in self.threads and self.threads[local_id].is_alive():
                continue
            if self.configurations[local_id] != (envelope.driver, envelope.configuration):
                raise ValueError("Batch configuration does not match its printer")
            if self.journal.row(envelope.batch_id)["phase"] == "prepared":
                executor.control.clear()
            go = self.request(
                "POST",
                f"/api/companion/batches/{envelope.batch_id}/ready",
                json={"digest": transfer["digest"]},
            ).json()
            if go["cancelled"]:
                self.journal.cancel(envelope.batch_id)
                continue
            self.journal.authorize(envelope.batch_id, transfer["digest"], go["go_token"])
            if self.stop.is_set():
                return
            if transfer.get("stop_mode"):
                executor.control.request(transfer["stop_mode"])
            thread = Thread(
                target=executor.execute,
                args=(envelope.model_dump(),),
                name=f"device-{local_id}",
                daemon=True,
            )
            self.threads[local_id] = thread
            thread.start()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                self.sync()
            except (httpx.HTTPError, ValueError, KeyError, OSError, json.JSONDecodeError):
                self.last_contact = 0
            self.stop.wait(2)

    def close(self, *, sync_threads: tuple[Thread, ...] = (), timeout: float = 30) -> None:
        from companion.shutdown import join_workers

        self.stop.set()
        deadline = time.monotonic() + timeout
        join_workers(sync_threads, deadline)
        join_workers(tuple(self.threads.values()), deadline)
        self.client.close()
