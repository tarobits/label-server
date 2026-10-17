"""Notification configuration is authorized, secret-masked, and never publishes."""

import pytest
from sqlalchemy import select
from test_access_security import accounts as account_fixture

from app.models import Notification, NotificationDelivery, NotificationEndpoint

accounts = account_fixture

DEFAULT_PRIORITIES = {
    "general": 3,
    "empty_tape": 4,
    "printer_blocked": 4,
    "batch_review": 4,
    "tape_waiting": 3,
    "approval_digest": 3,
}


def configuration(**overrides):
    return {
        "name": "Operations",
        "url": "https://ntfy.example",
        "topic": "label_alerts-1",
        "enabled": True,
        "destination_ids": ["main"],
        "all_printers": False,
        "kinds": ["empty_tape", "batch_review"],
        **overrides,
    }


def create(admin, **overrides):
    response = admin.post("/api/admin/notification-endpoints", json=configuration(**overrides))
    assert response.status_code == 201, response.text
    assert "token" not in response.json()
    return response.json()


def pending_delivery(admin, endpoint, *, delivered=False):
    with admin.app.state.factory.begin() as session:
        notice = Notification(
            title="Tape is empty",
            message="Cassette 1",
            path="/#/printers",
            kind="empty_tape",
            context={"printer_id": "main"},
        )
        session.add(notice)
        session.flush()
        delivery = NotificationDelivery(
            notification_id=notice.id,
            endpoint_id=endpoint["id"],
            endpoint_revision=endpoint["revision"],
            endpoint_name=endpoint["name"],
            delivered_at=123 if delivered else None,
        )
        session.add(delivery)
        session.flush()
        return delivery.id


def test_crud_masks_token_and_never_contacts_server(accounts, monkeypatch):
    admin, _, _ = accounts

    def no_publish(*args, **kwargs):
        pytest.fail("Configuring notification endpoints must never publish a message")

    monkeypatch.setattr("httpx.post", no_publish)
    endpoint = create(
        admin, name="  Operations  ", url="HTTPS://NTFY.EXAMPLE/base///", token="private-token"
    )
    assert endpoint["name"] == "Operations"
    assert endpoint["url"] == "https://ntfy.example/base"
    assert endpoint["has_token"] is True
    assert endpoint["revision"] == 1
    listed = admin.get("/api/admin/notification-endpoints")
    assert listed.status_code == 200
    assert listed.json() == [endpoint]
    assert "private-token" not in listed.text
    response = admin.put(
        f"/api/admin/notification-endpoints/{endpoint['id']}",
        json=configuration(name="Renamed", url=endpoint["url"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_token"] is True
    assert "token" not in response.json()
    assert response.json()["revision"] == 2
    assert admin.delete(f"/api/admin/notification-endpoints/{endpoint['id']}").status_code == 204
    assert admin.get("/api/admin/notification-endpoints").json() == []
    with admin.app.state.factory() as session:
        stored = session.get(NotificationEndpoint, endpoint["id"])
        assert stored.deleted_at is not None
        assert not stored.enabled
    assert (
        admin.put(
            f"/api/admin/notification-endpoints/{endpoint['id']}", json=configuration()
        ).status_code
        == 404
    )
    assert admin.delete(f"/api/admin/notification-endpoints/{endpoint['id']}").status_code == 404


def test_nonadministrator_and_missing_csrf_cannot_configure_endpoints(accounts):
    admin, alice, bob = accounts
    endpoint = create(admin)
    path = f"/api/admin/notification-endpoints/{endpoint['id']}"
    for member in (alice, bob):
        for response in (
            member.get("/api/admin/notification-endpoints"),
            member.post("/api/admin/notification-endpoints", json=configuration()),
            member.put(path, json=configuration()),
            member.delete(path),
        ):
            assert response.status_code == 403, response.text
    csrf = admin.headers.pop("X-CSRF-Token")
    try:
        assert admin.get("/api/admin/notification-endpoints").status_code == 200
        assert (
            admin.post("/api/admin/notification-endpoints", json=configuration()).status_code == 403
        )
        assert admin.put(path, json=configuration()).status_code == 403
        assert admin.delete(path).status_code == 403
    finally:
        admin.headers["X-CSRF-Token"] = csrf
    assert len(admin.get("/api/admin/notification-endpoints").json()) == 1


@pytest.mark.parametrize("token_input", [{}, {"token": None}, {"token": "private-token"}])
def test_unchanged_token_and_reordered_filters_preserve_revision_and_pending_delivery(
    accounts, token_input
):
    admin, _, _ = accounts
    endpoint = create(admin, token="private-token")
    delivery_id = pending_delivery(admin, endpoint)
    response = admin.put(
        f"/api/admin/notification-endpoints/{endpoint['id']}",
        json=configuration(kinds=["batch_review", "empty_tape"], **token_input),
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert response.json()["has_token"]
    with admin.app.state.factory() as session:
        assert session.get(NotificationEndpoint, endpoint["id"]).token == "private-token"
        assert not session.get(NotificationDelivery, delivery_id).cancelled


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"url": "https://ntfy.example/another-server"},
        {"topic": "other_topic"},
        {"token": "replacement-token"},
        {"token": ""},
        {"destination_ids": [], "all_printers": True},
        {"kinds": ["empty_tape"]},
    ],
)
def test_configuration_change_cancels_only_this_endpoints_pending_deliveries(accounts, changes):
    admin, _, _ = accounts
    endpoint = create(admin, token="private-token")
    other = create(admin, name="Other endpoint")
    pending = pending_delivery(admin, endpoint)
    completed = pending_delivery(admin, endpoint, delivered=True)
    other_pending = pending_delivery(admin, other)
    response = admin.put(
        f"/api/admin/notification-endpoints/{endpoint['id']}", json=configuration(**changes)
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert "token" not in result
    assert result["revision"] == 2
    assert result["has_token"] is (changes.get("token") != "")
    with admin.app.state.factory() as session:
        assert session.get(NotificationDelivery, pending).cancelled
        assert not session.get(NotificationDelivery, completed).cancelled
        assert not session.get(NotificationDelivery, other_pending).cancelled
        parent_id = session.get(NotificationDelivery, pending).notification_id
        assert session.get(Notification, parent_id).cancelled
        if "token" in changes:
            assert session.get(NotificationEndpoint, endpoint["id"]).token == changes["token"]


def test_delete_soft_deletes_and_cancels_pending_delivery(accounts):
    admin, _, _ = accounts
    endpoint = create(admin)
    pending = pending_delivery(admin, endpoint)
    completed = pending_delivery(admin, endpoint, delivered=True)
    response = admin.delete(f"/api/admin/notification-endpoints/{endpoint['id']}")
    assert response.status_code == 204
    assert response.content == b""
    with admin.app.state.factory() as session:
        assert session.get(NotificationEndpoint, endpoint["id"]).revision == 2
        assert session.get(NotificationDelivery, pending).cancelled
        assert not session.get(NotificationDelivery, completed).cancelled
        parent_id = session.get(NotificationDelivery, pending).notification_id
        assert session.get(Notification, parent_id).cancelled


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"name": "a" * 101},
        {"url": "ftp://ntfy.example"},
        {"url": "https://user:secret@ntfy.example"},
        {"url": "https://@ntfy.example"},
        {"url": "https://ntfy.example?topic=labels"},
        {"url": "https://ntfy.example#labels"},
        {"url": "https://ntfy.example:99999"},
        {"url": "https://ntfy.example/path with spaces"},
        {"url": "https://ntfy.example/\x00"},
        {"url": "https://ntfy.example\\other"},
        {"url": "https://"},
        {"topic": ""},
        {"topic": "a" * 65},
        {"topic": "topic/path"},
        {"topic": "topic.name"},
        {"topic": "topic name"},
        {"kinds": []},
        {"kinds": ["unknown"]},
        {"kinds": ["empty_tape", "empty_tape"]},
        {"minimum_level": "request"},
        {"role_ids": []},
        {"destination_ids": []},
        {"all_printers": True},
        {"destination_ids": ["missing"]},
        {"destination_ids": ["main", "main"]},
    ],
)
def test_invalid_configuration_does_not_create_an_endpoint(accounts, changes):
    admin, _, _ = accounts
    response = admin.post("/api/admin/notification-endpoints", json=configuration(**changes))
    assert response.status_code == 422, response.text
    assert admin.get("/api/admin/notification-endpoints").json() == []
    with admin.app.state.factory() as session:
        assert not list(session.scalars(select(NotificationEndpoint)))


def test_retired_printer_cannot_be_selected_and_invalid_update_preserves_endpoint(accounts):
    from app.models import PrinterDevice

    admin, _, _ = accounts
    endpoint = create(admin)
    pending = pending_delivery(admin, endpoint)
    with admin.app.state.factory.begin() as session:
        printer = session.get(PrinterDevice, "main")
        printer.config = {**printer.config, "retired": True}
    response = admin.put(
        f"/api/admin/notification-endpoints/{endpoint['id']}",
        json=configuration(destination_ids=["main"]),
    )
    assert response.status_code == 422, response.text
    assert admin.get("/api/admin/notification-endpoints").json() == [endpoint]
    with admin.app.state.factory() as session:
        assert not session.get(NotificationDelivery, pending).cancelled


def test_http_ipv6_base_path_and_distribution_group_references_are_supported(accounts):
    admin, _, _ = accounts
    response = admin.post(
        "/api/printer-groups", json={"name": "Notification station", "printer_ids": ["main"]}
    )
    assert response.status_code == 201, response.text
    group = response.json()
    endpoint = create(
        admin,
        url="http://[::1]:8080/ntfy/",
        destination_ids=[group["id"]],
        kinds=["general"],
    )
    assert endpoint["url"] == "http://[::1]:8080/ntfy"
    assert endpoint["destination_ids"] == [group["id"]]
    assert endpoint["all_printers"] is False
    assert "role_ids" not in endpoint
    assert "minimum_level" not in endpoint


def test_explicit_all_printers_and_global_only_defaults(accounts):
    admin, _, _ = accounts
    all_printers = create(admin, destination_ids=[], all_printers=True)
    assert all_printers["all_printers"] is True
    assert all_printers["destination_ids"] == []
    payload = configuration(destination_ids=[], kinds=["general", "approval_digest"])
    del payload["all_printers"]
    response = admin.post("/api/admin/notification-endpoints", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["all_printers"] is False
    assert response.json()["destination_ids"] == []


def test_priority_defaults_partial_overrides_and_changes_cancel_pending_deliveries(accounts):
    admin, _, _ = accounts
    endpoint = create(admin, priorities={"empty_tape": 5})
    priorities = {**DEFAULT_PRIORITIES, "empty_tape": 5}
    assert endpoint["priorities"] == priorities
    delivery_id = pending_delivery(admin, endpoint)
    response = admin.put(
        f"/api/admin/notification-endpoints/{endpoint['id']}",
        json=configuration(priorities=priorities),
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    with admin.app.state.factory() as session:
        assert not session.get(NotificationDelivery, delivery_id).cancelled
    response = admin.put(
        f"/api/admin/notification-endpoints/{endpoint['id']}",
        json=configuration(priorities={"batch_review": 1, "empty_tape": 5}),
    )
    assert response.status_code == 200, response.text
    assert response.json()["priorities"] == {**priorities, "batch_review": 1}
    assert response.json()["revision"] == 2
    with admin.app.state.factory() as session:
        assert session.get(NotificationDelivery, delivery_id).cancelled
    assert create(admin, name="Defaults")["priorities"] == DEFAULT_PRIORITIES


@pytest.mark.parametrize(
    "priorities",
    [
        {"empty_tape": 0},
        {"empty_tape": 6},
        {"empty_tape": True},
        {"empty_tape": 1.5},
        {"empty_tape": "5"},
        {"unknown_kind": 3},
        {"empty_tape": None},
        None,
    ],
)
def test_priorities_accept_only_known_kinds_with_strict_integer_values(accounts, priorities):
    admin, _, _ = accounts
    response = admin.post(
        "/api/admin/notification-endpoints", json=configuration(priorities=priorities)
    )
    assert response.status_code == 422, response.text
    assert admin.get("/api/admin/notification-endpoints").json() == []


@pytest.mark.parametrize("kind", ["empty_tape", "printer_blocked", "batch_review", "tape_waiting"])
def test_operational_kind_requires_explicit_printer_scope_on_create_and_update(accounts, kind):
    admin, _, _ = accounts
    unsafe = configuration(destination_ids=[], kinds=[kind])
    assert admin.post("/api/admin/notification-endpoints", json=unsafe).status_code == 422
    endpoint = create(admin)
    delivery_id = pending_delivery(admin, endpoint)
    assert (
        admin.put(f"/api/admin/notification-endpoints/{endpoint['id']}", json=unsafe).status_code
        == 422
    )
    assert admin.get("/api/admin/notification-endpoints").json() == [endpoint]
    with admin.app.state.factory() as session:
        assert not session.get(NotificationDelivery, delivery_id).cancelled
