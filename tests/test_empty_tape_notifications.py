import time

import pytest
from alembic import command
from alembic.config import Config
from conftest import install, profile
from sqlalchemy import select, text
from test_notifications import Sender

from app.db import make_engine, session_factory
from app.identity import LOCAL_OWNER_ID
from app.models import AuthSettings, Notification, User
from app.notifications import deliver_pending, enqueue


def empty_alert(client, *, administrator=True):
    tape = profile(client, threshold=100)
    cartridge = install(client, tape["id"], remaining=0)
    if administrator:
        with client.app.state.factory.begin() as session:
            session.add(
                User(
                    id=LOCAL_OWNER_ID,
                    username="admin",
                    password_hash="unused",
                    role_ids=["administrator"],
                )
            )
            session.get(AuthSettings, 1).approval_notifications_enabled = False
    client.app.state.fleet.workers["main"].tick()
    with client.app.state.factory() as session:
        notice = session.scalar(select(Notification).where(Notification.kind == "empty_tape"))
        assert notice is not None
        return cartridge, notice.id


def test_admin_empty_alert_delivers_without_pending_requests_or_approval_notifications(client):
    cartridge, identifier = empty_alert(client)
    sender = Sender()
    now = time.time() + 1
    deliver_pending(client.app.state.factory, sender, now)
    assert sender.sent == [identifier]
    with client.app.state.factory() as session:
        notice = session.get(Notification, identifier)
        assert notice.recipient_id == "administrators"
        assert notice.context == {"printer_id": "main", "cartridge_id": cartridge["id"]}
        assert "Mock printer" in notice.message
        assert "Cassette 1" in notice.message
        assert "0 mm" in notice.message
        assert "approval" not in notice.message
        assert notice.delivered_at == now


def test_empty_alert_retry_does_not_create_batches_or_duplicate_alerts(client):
    _, identifier = empty_alert(client)
    sender = Sender()
    sender.fail = True
    now = time.time() + 1
    deliver_pending(client.app.state.factory, sender, now)
    client.app.state.fleet.workers["main"].tick()
    sender.fail = False
    deliver_pending(client.app.state.factory, sender, now + 29)
    assert not sender.sent
    deliver_pending(client.app.state.factory, sender, now + 30)
    assert sender.sent == [identifier]
    assert client.get("/api/batches").json() == []
    assert len(client.get("/api/notifications").json()) == 1


@pytest.mark.parametrize("resolution", ["refill", "uninstall", "retire"])
def test_recovered_empty_alert_is_not_delivered(client, resolution):
    cartridge, identifier = empty_alert(client)
    if resolution == "refill":
        response = client.put(
            f"/api/cartridges/{cartridge['id']}/remaining", json={"remaining_mm": 1000}
        )
        assert response.status_code == 200, response.text
        assert client.get("/api/status").json()["blocker"] is None
    elif resolution == "uninstall":
        assert (
            client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 200
        )
    else:
        from app.models import PrinterDevice

        with client.app.state.factory.begin() as session:
            session.get(PrinterDevice, "main").config = {"retired": True}
    sender = Sender()
    deliver_pending(client.app.state.factory, sender, time.time() + 1)
    assert not sender.sent
    with client.app.state.factory() as session:
        assert session.get(Notification, identifier).cancelled


def test_refill_then_empty_again_cancels_old_alert_and_sends_one_new_episode(client):
    cartridge, first = empty_alert(client)
    for remaining in (1000, 0):
        response = client.put(
            f"/api/cartridges/{cartridge['id']}/remaining", json={"remaining_mm": remaining}
        )
        assert response.status_code == 200, response.text
    client.app.state.fleet.workers["main"].tick()
    sender = Sender()
    deliver_pending(client.app.state.factory, sender, time.time() + 1)
    assert len(sender.sent) == 1
    assert sender.sent[0] != first


def test_empty_alert_waits_for_initial_administrator_setup(client):
    _, identifier = empty_alert(client, administrator=False)
    sender = Sender()
    now = time.time() + 1
    deliver_pending(client.app.state.factory, sender, now)
    assert not sender.sent
    with client.app.state.factory.begin() as session:
        assert not session.get(Notification, identifier).cancelled
        session.add(
            User(
                id=LOCAL_OWNER_ID,
                username="admin",
                password_hash="unused",
                role_ids=["administrator"],
            )
        )
    deliver_pending(client.app.state.factory, sender, now + 1)
    assert sender.sent == [identifier]


def test_delivery_rechecks_cancellation_after_an_earlier_notice_is_sent(client):
    with client.app.state.factory.begin() as session:
        enqueue(session, "Earlier notice", "Earlier notice", "/", now=0)
    cartridge, old_alert = empty_alert(client)

    class RefillingSender(Sender):
        def send(self, notification):
            super().send(notification)
            if notification.title != "Earlier notice":
                return
            # While the delivery loop is outside its transaction, start a fresh
            # depletion episode. The old ID is still in its initial snapshot.
            for remaining in (8000, 0):
                assert (
                    client.put(
                        f"/api/cartridges/{cartridge['id']}/remaining",
                        json={"remaining_mm": remaining},
                    ).status_code
                    == 200
                )
            client.app.state.fleet.workers["main"].tick()

    sender = RefillingSender()
    now = time.time() + 1
    deliver_pending(client.app.state.factory, sender, now)
    assert len(sender.sent) == 1
    assert old_alert not in sender.sent
    with client.app.state.factory() as session:
        old = session.get(Notification, old_alert)
        assert old.cancelled
        assert old.delivered_at is None
    deliver_pending(client.app.state.factory, sender, now + 10)
    assert len(sender.sent) == 2
    assert old_alert not in sender.sent


def test_existing_admin_digests_migrate_without_changing_ordinary_notifications(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "e84a91c607d2")
    engine = make_engine(url)
    try:
        with engine.begin() as connection:
            for identifier, recipient in (
                ("digest", "administrators"),
                ("ordinary", LOCAL_OWNER_ID),
            ):
                connection.execute(
                    text(
                        "INSERT INTO notifications (id, recipient_id, title, message, path, created_at, next_attempt_at, attempts, cancelled) VALUES (:id, :recipient, 'Title', 'Message', '/', 1, 1, 0, 0)"
                    ),
                    {"id": identifier, "recipient": recipient},
                )
        command.upgrade(config, "head")
        with session_factory(engine)() as session:
            assert session.get(Notification, "digest").kind == "approval_digest"
            assert session.get(Notification, "ordinary").kind == "general"
            assert session.get(Notification, "digest").context == {}
        command.downgrade(config, "e84a91c607d2")
        command.upgrade(config, "head")
    finally:
        engine.dispose()
