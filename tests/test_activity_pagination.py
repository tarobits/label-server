"""Complete activity history, stable pages, and authorization before counting."""

import time

import pytest
from conftest import profile
from test_access_security import accounts as account_fixture

from app.models import Batch, Notification, PrinterDevice, Role, State

accounts = account_fixture


def seed_batches(client, count=137, printer_id="main", prefix="batch"):
    cartridge = client.post(
        "/api/cartridges",
        json={
            "name": prefix,
            "profile_id": profile(client, name=prefix)["id"],
            "nominal_length_mm": 8000,
        },
    ).json()
    with client.app.state.factory.begin() as session:
        for index in range(count):
            session.add(
                Batch(
                    id=f"{prefix}-{index:03d}",
                    printer_id=printer_id,
                    cartridge_id=cartridge["id"],
                    state=State.FAILED,
                    created_at=1000 + index // 3,
                    estimated_mm=0,
                    error="Rejected before printing",
                )
            )
    return cartridge


def seed_notifications(client, count=137):
    with client.app.state.factory.begin() as session:
        for index in range(count):
            session.add(
                Notification(
                    id=f"notice-{index:03d}",
                    title=f"Notice {index}",
                    message="Saved test event",
                    path="/#/activity",
                    created_at=1000 + index // 3,
                )
            )


@pytest.mark.parametrize("resource", ["batches", "notifications"])
def test_all_history_is_reachable_with_stable_ties_and_a_snapshot(client, resource):
    cartridge = seed_batches(client) if resource == "batches" else None
    if resource == "notifications":
        seed_notifications(client)
    first = client.get(f"/api/{resource}/page?limit=25").json()
    assert first["total"] == 137
    seen = []
    for offset in range(0, 150, 25):
        page = client.get(
            f"/api/{resource}/page", params={"offset": offset, "before": first["before"]}
        )
        assert page.status_code == 200, page.text
        assert page.json()["total"] == 137
        seen.extend(item["id"] for item in page.json()["items"])
    assert len(seen) == len(set(seen)) == 137
    prefix = "batch" if resource == "batches" else "notice"
    assert seen == [
        f"{prefix}-{i:03d}" for i in sorted(range(137), key=lambda i: (-(1000 + i // 3), i))
    ]
    with client.app.state.factory.begin() as session:
        session.add(
            Batch(
                id="new",
                printer_id="main",
                cartridge_id=cartridge["id"],
                estimated_mm=0,
                state=State.FAILED,
                created_at=time.time(),
            )
            if cartridge
            else Notification(
                id="new",
                title="New",
                message="New event",
                path="/#/activity",
                created_at=time.time(),
            )
        )
    frozen = client.get(f"/api/{resource}/page", params={"before": first["before"]}).json()
    assert frozen == first
    latest = client.get(f"/api/{resource}/page").json()
    assert latest["total"] == 138 and latest["items"][0]["id"] == "new"
    assert client.get(f"/api/{resource}/page?offset=1000").json()["items"] == []
    # Existing consumers of the compact list keep their response shape.
    assert len(client.get(f"/api/{resource}").json()) == 100


def test_batch_page_totals_and_offsets_only_include_authorized_printers(accounts):
    admin, alice, bob = accounts
    seed_batches(admin, count=30)
    with admin.app.state.factory.begin() as session:
        session.add(PrinterDevice(id="private", name="Private", driver="mock", config={}))
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "moderator"}
        ]
    seed_batches(admin, count=110, printer_id="private", prefix="hidden")
    page = alice.get("/api/batches/page?offset=25").json()
    assert page["total"] == 30 and len(page["items"]) == 5
    assert all(item["printer_id"] == "main" for item in page["items"])
    assert admin.get("/api/batches/page").json()["total"] == 140
    assert bob.get("/api/batches/page").json()["total"] == 0
    assert bob.get("/api/batches/page").json()["items"] == []
    assert alice.get("/api/notifications/page").status_code == 403
    assert bob.get("/api/notifications/page").status_code == 403


@pytest.mark.parametrize("resource", ["batches", "notifications"])
@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "before=nan", "before=inf", "before=-1"]
)
def test_history_page_rejects_invalid_pagination(client, resource, query):
    assert client.get(f"/api/{resource}/page?{query}").status_code == 422
