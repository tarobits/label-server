import time

import httpx
import pytest
from conftest import install, job, profile
from fastapi.testclient import TestClient

from app.config import Settings
from app.models import Notification
from app.notifications import NtfySender, deliver_pending


class Sender:
    def __init__(self) -> None:
        self.fail = False
        self.sent: list[str] = []

    def send(self, notification: Notification) -> None:
        if self.fail:
            raise OSError("network unavailable")
        self.sent.append(notification.id)


def test_waiting_repeat_silence_episode_reset(client: TestClient) -> None:
    white = profile(client)
    yellow = profile(client, "Yellow", threshold=2, reminders=True)
    install(client, white["id"])
    item = job(client, yellow["id"], 2)
    worker = client.app.state.worker
    factory = client.app.state.factory
    now = time.time()
    sender = Sender()
    worker.tick(now)
    deliver_pending(factory, sender, now)
    assert len(sender.sent) == 1
    worker.tick(now + 59)
    deliver_pending(factory, sender, now + 59)
    assert len(sender.sent) == 1
    worker.tick(now + 60)
    deliver_pending(factory, sender, now + 60)
    assert len(sender.sent) == 2
    client.put(f"/api/tape-profiles/{yellow['id']}/reminder", json={"action": "silence"})
    worker.tick(now + 120)
    deliver_pending(factory, sender, now + 120)
    assert len(sender.sent) == 2
    client.delete(f"/api/jobs/{item['id']}")
    worker.tick(now + 121)
    job(client, yellow["id"], 2)
    worker.tick(now + 122)
    deliver_pending(factory, sender, now + 122)
    assert len(sender.sent) == 3


def test_snooze_and_stale_reminders(client: TestClient) -> None:
    tape = profile(client, threshold=1, reminders=True)
    job(client, tape["id"])
    now = time.time()
    worker = client.app.state.worker
    sender = Sender()
    worker.tick(now)
    client.put(
        f"/api/tape-profiles/{tape['id']}/reminder", json={"action": "snooze", "until": now + 120}
    )
    deliver_pending(client.app.state.factory, sender, now)
    worker.tick(now + 119)
    assert not sender.sent
    worker.tick(now + 120)
    deliver_pending(client.app.state.factory, sender, now + 120)
    assert len(sender.sent) == 1
    worker.tick(now + 180)
    install(client, tape["id"])
    deliver_pending(client.app.state.factory, sender, now + 180)
    assert len(sender.sent) == 1


def test_delivery_retry_does_not_repeat_printing(client: TestClient) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"])
    worker = client.app.state.worker
    worker.backend.fail_after = 0
    worker.tick()
    now = time.time()
    sender = Sender()
    sender.fail = True
    deliver_pending(client.app.state.factory, sender, now)
    assert client.get("/api/notifications").json()[0]["attempts"] == 1
    sender.fail = False
    deliver_pending(client.app.state.factory, sender, now + 29)
    assert not sender.sent
    deliver_pending(client.app.state.factory, sender, now + 30)
    worker.tick()
    assert len(sender.sent) == 1
    assert len(worker.backend.batches) == 1


def test_ntfy_payload_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "accepted"})

    with httpx.Client(transport=httpx.MockTransport(capture)) as http:
        monkeypatch.setattr(httpx, "post", http.post)
        settings = Settings(
            ntfy_url="https://ntfy.example",
            ntfy_topic="labels",
            ntfy_token="test-token",
            public_url="https://labels.example",
        )
        NtfySender(settings).send(
            Notification(title="Tape swap needed", message="Yellow cassette", path="/")
        )
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-token"
    assert b'"topic":"labels"' in requests[0].content
    assert b'"click":"https://labels.example/"' in requests[0].content


def test_episode_resets_between_worker_ticks(client: TestClient) -> None:
    tape = profile(client, threshold=1, reminders=True)
    queued = job(client, tape["id"])
    client.put(f"/api/tape-profiles/{tape['id']}/reminder", json={"action": "silence"})
    client.delete(f"/api/jobs/{queued['id']}")
    job(client, tape["id"])
    assert not client.get("/api/tape-profiles").json()[0]["reminder_silenced"]
