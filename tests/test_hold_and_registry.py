import pytest
from conftest import install, job, profile
from fastapi.testclient import TestClient

from app.models import PrinterState
from app.printer.registry import (
    MediaKind,
    NetworkConnection,
    PrinterCapabilities,
    PrinterDefinition,
    PrinterRegistry,
)
from app.queue import QueueWorker


def test_hold_survives_new_worker_and_allows_manual_flush(client: TestClient) -> None:
    tape = profile(client, threshold=2)
    install(client, tape["id"])
    assert client.put("/api/printer/automatic-printing", json={"held": True}).status_code == 200
    job(client, tape["id"], 5)
    worker = QueueWorker(client.app.state.factory, client.app.state.worker.backend)
    worker.tick()
    assert not worker.backend.batches
    with client.app.state.factory() as session:
        assert session.get(PrinterState, 1).automatic_printing_held
    client.post("/api/queue/print")
    worker.tick()
    assert len(worker.backend.batches[0]) == 5
    job(client, tape["id"], 3)
    worker.tick()
    assert len(worker.backend.batches) == 1
    client.put("/api/printer/automatic-printing", json={"held": False})
    worker.tick()
    assert len(worker.backend.batches[1]) == 3


def test_hold_never_bypasses_review(client: TestClient) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    worker = client.app.state.worker
    worker.backend.fail_after = 0
    job(client, tape["id"])
    worker.tick()
    client.put("/api/printer/automatic-printing", json={"held": True})
    client.put("/api/printer/automatic-printing", json={"held": False})
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert client.post("/api/queue/print").status_code == 409


def test_shipping_wifi_definition_needs_an_explicit_driver() -> None:
    registry = PrinterRegistry()
    device = PrinterDefinition(
        "shipping",
        "Shipping printer",
        "unimplemented",
        NetworkConnection(host="printer.local", port=631, protocol="ipp", link="wifi"),
        PrinterCapabilities(MediaKind.FIXED_LABEL, 203, 203, (102,), 2, ((102, 152),)),
    )
    registry.register(device)
    assert registry.definition("shipping").connection.link == "wifi"
    with pytest.raises(ValueError, match="no enabled driver"):
        registry.backend("shipping")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(device)
