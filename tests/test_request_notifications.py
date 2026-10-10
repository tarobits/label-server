"""Approval summaries persist independently of printer execution and delivery retries."""

from types import SimpleNamespace

from conftest import profile
from sqlalchemy import func, select

from app.db import make_engine, session_factory
from app.identity import LOCAL_OWNER_ID
from app.models import AuthSettings, Notification, PrintJob, User
from app.notifications import deliver_pending
from app.request_models import PrintRequest, RequestDigest
from app.request_notifications import schedule_request_digest


class Sender:
    def __init__(self):
        self.fail = False
        self.sent = []

    def send(self, notification):
        if self.fail:
            raise OSError("Temporary notification failure")
        self.sent.append((notification.id, notification.message, notification.recipient_id))


def prepare(client):
    with client.app.state.factory.begin() as session:
        session.add(
            User(
                id=LOCAL_OWNER_ID,
                username="administrator",
                password_hash="unused",
                role_ids=["administrator"],
            )
        )
    tape = profile(client)
    return {"kind": "job", "input": {"tape_profile": tape["id"], "data": {"text": "Pending"}}}


def tick(factory, now):
    with factory.begin() as session:
        schedule_request_digest(session, now)


def test_fifty_requests_coalesce_into_fixed_persistent_window(client, monkeypatch):
    body = prepare(client)
    now = [1000.0]
    monkeypatch.setattr("app.request_api.time", SimpleNamespace(time=lambda: now[0]))
    for index in range(50):
        now[0] = 1000 + index
        response = client.post("/api/requests", json=body)
        assert response.status_code == 201, response.text
    with client.app.state.factory() as session:
        digest = session.get(RequestDigest, 1)
        assert digest.first_at == 1000
        assert digest.due_at == 1060
        assert digest.count == 50
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 0
    # Reopening the persisted database proves the window is not a process timer.
    engine = make_engine(client.app.state.settings.database_url)
    fresh_factory = session_factory(engine)
    try:
        tick(fresh_factory, 1059)
        with fresh_factory() as session:
            assert session.scalar(select(func.count()).select_from(Notification)) == 0
        tick(fresh_factory, 1060)
        tick(fresh_factory, 1061)
        with fresh_factory() as session:
            notices = list(session.scalars(select(Notification)))
            assert len(notices) == 1
            assert notices[0].message == "50 print request(s) await administrator review."
            assert notices[0].recipient_id == "administrators"
            assert session.get(RequestDigest, 1) is None
        now[0] = 1070
        assert client.post("/api/requests", json=body).status_code == 201
        with fresh_factory() as session:
            assert session.get(RequestDigest, 1).due_at == 1130
    finally:
        engine.dispose()


def test_disabled_notifications_drop_pending_window_and_cancel_unsent_summary(client, monkeypatch):
    body = prepare(client)
    monkeypatch.setattr("app.request_api.time", SimpleNamespace(time=lambda: 1000))
    assert client.post("/api/requests", json=body).status_code == 201
    factory = client.app.state.factory
    with factory.begin() as session:
        session.get(AuthSettings, 1).approval_notifications_enabled = False
    tick(factory, 1060)
    with factory.begin() as session:
        assert session.get(RequestDigest, 1) is None
        assert session.scalar(select(func.count()).select_from(Notification)) == 0
        session.get(AuthSettings, 1).approval_notifications_enabled = True
    assert client.post("/api/requests", json=body).status_code == 201
    tick(factory, 1060)
    with factory.begin() as session:
        session.get(AuthSettings, 1).approval_notifications_enabled = False
    sender = Sender()
    deliver_pending(factory, sender, 1060)
    assert not sender.sent
    with factory() as session:
        assert session.scalar(select(Notification)).cancelled


def test_approval_notification_retry_never_creates_executable_jobs(client, monkeypatch):
    body = prepare(client)
    monkeypatch.setattr("app.request_api.time", SimpleNamespace(time=lambda: 1000))
    response = client.post("/api/requests", json=body)
    assert response.status_code == 201, response.text
    factory = client.app.state.factory
    tick(factory, 1060)
    sender = Sender()
    sender.fail = True
    deliver_pending(factory, sender, 1060)
    with factory() as session:
        assert session.scalar(select(Notification)).attempts == 1
    sender.fail = False
    deliver_pending(factory, sender, 1089)
    assert not sender.sent
    deliver_pending(factory, sender, 1090)
    deliver_pending(factory, sender, 1200)
    assert len(sender.sent) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 0
        assert session.get(PrintRequest, response.json()["id"]).status == "pending"


def test_no_summary_when_pending_requests_already_resolved(client, monkeypatch):
    body = prepare(client)
    monkeypatch.setattr("app.request_api.time", SimpleNamespace(time=lambda: 1000))
    value = client.post("/api/requests", json=body).json()
    with client.app.state.factory.begin() as session:
        session.get(PrintRequest, value["id"]).status = "rejected"
    tick(client.app.state.factory, 1060)
    with client.app.state.factory() as session:
        assert session.get(RequestDigest, 1) is None
        assert session.scalar(select(func.count()).select_from(Notification)) == 0
