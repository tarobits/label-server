"""Requester cost conservation, private reporting and uncertain print attempts."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_print_audit import direct, grant, prepare_printer

from app.models import Batch, Cartridge, TapeAllocation
from app.printer.base import PrintNotStarted, PrintResult
from app.usage import distribute, settle_usage

accounts = account_fixture


def price(admin, minor=2000, currency="EUR"):
    cartridge = admin.get("/api/cartridges").json()[0]
    response = admin.put(
        f"/api/cartridges/{cartridge['id']}/price",
        json={
            "price_minor": minor,
            "currency": currency,
        },
    )
    assert response.status_code == 200, response.text
    return cartridge


def report(client, all_users=False):
    response = client.get(f"/api/usage?all_users={str(all_users).lower()}")
    assert response.status_code == 200, response.text
    return response.json()


def test_shared_leader_and_all_tape_charge_requesters_not_manual_starter(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    grant(admin, "bob", "print")
    tape, worker = prepare_printer(admin, threshold=100)
    cartridge = price(admin)
    a = direct(alice, tape, text="Same", copies=1)
    b = direct(bob, tape, text="Same", copies=3)
    assert a["length_mm"] == b["length_mm"]
    assert admin.post("/api/queue/print?printer_id=main").status_code == 202
    worker.tick()
    summary = report(admin, True)
    assert {user["user_id"] for user in summary["users"]} == {"alice", "bob"}
    attempt = admin.get("/api/batches").json()[0]
    by_user = {user["user_id"]: user for user in summary["users"]}
    assert by_user["alice"]["consumed_mm"] == pytest.approx(attempt["consumed_mm"] / 4, abs=0.001)
    assert sum(user["consumed_mm"] for user in summary["users"]) == pytest.approx(
        attempt["consumed_mm"], abs=0.001
    )
    costs = sum(Decimal(user["costs"]["EUR"]) for user in summary["users"])
    expected = Decimal(str(attempt["consumed_mm"])) / 8000 * 20
    assert costs == expected.quantize(Decimal("0.000001"))
    assert costs > Decimal(str(a["length_mm"] * 4 / 8000 * 20))  # Shared leader included.
    assert [user["user_id"] for user in report(alice)["users"]] == ["alice"]
    assert all(entry["user_id"] == "alice" for entry in report(alice)["entries"])
    assert report(admin)["users"] == []
    assert alice.get("/api/usage?all_users=true").status_code == 403
    assert (
        bob.put(f"/api/cartridges/{cartridge['id']}/price", json={"price_minor": 1}).status_code
        == 403
    )
    original = report(alice)
    price(admin, 4000, "USD")
    assert report(alice) == original  # Historical price and currency remain frozen.
    direct(alice, tape)
    assert admin.post("/api/queue/print?printer_id=main").status_code == 202
    worker.tick()
    assert set(report(alice)["users"][0]["costs"]) == {"EUR", "USD"}


def test_pending_review_reported_waste_and_retry_are_separate_idempotent_charges(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    price(admin)
    direct(alice, tape, copies=2)
    worker.backend.fail_after = 0
    worker.tick()
    pending = report(alice)
    assert pending["users"][0]["consumed_mm"] == 0
    assert pending["users"][0]["pending_mm"] > 0
    assert pending["users"][0]["costs"] == {}
    batch = admin.get("/api/batches").json()[0]
    detail = admin.get(f"/api/batches/{batch['id']}").json()
    assert (
        admin.put(
            f"/api/cartridges/{batch['cartridge_id']}/price", json={"price_minor": 5}
        ).status_code
        == 409
    )
    decisions = {item["copy_id"]: "queued" for item in detail["items"]}
    reviewed = admin.post(
        f"/api/batches/{batch['id']}/review", json={"decisions": decisions, "consumed_mm": 100}
    )
    assert reviewed.status_code == 200, reviewed.text
    assert report(alice)["users"][0]["costs"] == {"EUR": "0.250000"}
    with admin.app.state.factory.begin() as session:
        settle_usage(session, session.get(Batch, batch["id"]), 999)  # Never charge twice.
    assert report(alice)["users"][0]["consumed_mm"] == 100
    worker.tick()
    final = report(alice)
    assert len(final["entries"]) == 2
    assert final["users"][0]["pending_mm"] == 0
    assert final["users"][0]["consumed_mm"] > 100
    assert (
        admin.post(
            f"/api/batches/{batch['id']}/review", json={"decisions": decisions, "consumed_mm": 100}
        ).status_code
        == 409
    )


def test_unpriced_is_not_free_and_estimated_measured_sources_are_retained(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    direct(alice, tape)
    worker.backend.print_batch = lambda labels: PrintResult()
    worker.tick()
    original = report(alice)
    assert original["users"][0]["unpriced_mm"] > 0
    assert original["users"][0]["costs"] == {}
    assert original["entries"][0]["consumption_source"] == "estimated"
    price(admin, 0)
    assert report(alice) == original
    direct(alice, tape)
    worker.backend.print_batch = lambda labels: PrintResult(50)
    worker.tick()
    result = report(alice)
    assert result["users"][0]["costs"] == {"EUR": "0.000000"}
    assert result["users"][0]["unpriced_mm"] == original["users"][0]["unpriced_mm"]
    assert result["entries"][0]["consumed_mm"] == 50
    assert result["entries"][0]["consumption_source"] == "measured"


def test_no_charge_when_backend_guarantees_print_never_started(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    price(admin)
    direct(alice, tape)

    def no_print(labels):
        raise PrintNotStarted("Fixture rejected before hardware")

    worker.backend.print_batch = no_print
    worker.tick()
    result = report(alice)
    assert result["users"][0]["pending_mm"] == 0
    assert result["users"][0]["consumed_mm"] == 0
    assert result["users"][0]["costs"] == {"EUR": "0.000000"}


def test_price_registration_validation_and_legacy_attempts(client):
    from conftest import profile

    tape = profile(client)
    body = {
        "profile_id": tape["id"],
        "name": "Priced",
        "nominal_length_mm": 8000,
        "price_minor": 1299,
        "currency": "GBP",
    }
    saved = client.post("/api/cartridges", json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["price_minor"] == 1299
    for invalid in [-1, 0.5, True, 1000000001]:
        assert (
            client.post("/api/cartridges", json={**body, "price_minor": invalid}).status_code == 422
        )
    assert client.post("/api/cartridges", json={**body, "currency": "eu"}).status_code == 422
    with client.app.state.factory.begin() as session:
        batch = Batch(cartridge_id=saved.json()["id"], estimated_mm=100)
        session.add(batch)
        session.flush()
        settle_usage(session, batch, 100)
        assert list(session.scalars(select(TapeAllocation))) == []
        assert session.get(Cartridge, saved.json()["id"]).price_minor == 1299


def test_integer_allocation_conserves_even_tiny_charges():
    assert distribute(2, [Decimal(1)] * 3) == [1, 1, 0]
    assert distribute(100, [Decimal(1), Decimal(3)]) == [25, 75]
    assert distribute(1, [Decimal(0), Decimal(0)]) == [1, 0]


def test_brother_floor_feed_and_template_padding_are_in_requester_total(client):
    from conftest import install, profile
    from test_cut_planning import configure_brother, short_document

    worker, _ = configure_brother(client)
    tape = profile(client, threshold=1, width=12)
    cartridge = install(client, tape["id"])
    price(client)
    template = client.post(
        "/api/templates", json={"name": "Tiny", "document": short_document()}
    ).json()
    queued = client.post(
        "/api/jobs",
        json={"template": template["id"], "tape_profile": tape["id"], "copies": 2, "data": {}},
    )
    assert queued.status_code == 201, queued.text
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    usage = report(client)
    total = usage["users"][0]["consumed_mm"]
    assert total == 73.5  # Two 24.5 mm cut pieces and one 24.5 mm leader.
    assert total == pytest.approx(sum(batch["print_plan"]["breakdown"].values()))
    assert batch["print_plan"]["breakdown"]["unused_mm"] > 0
    remaining = client.get("/api/cartridges").json()[0]["remaining_mm"]
    assert total == cartridge["remaining_mm"] - remaining
    assert usage["users"][0]["costs"] == {"EUR": "0.183750"}


def test_approval_cost_belongs_to_original_requester(accounts):
    admin, alice, bob = accounts
    grant(admin, "bob", "moderator")
    tape, worker = prepare_printer(admin, threshold=100)
    price(admin)
    requested = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "destination_id": "main",
                "tape_profile": tape["id"],
                "data": {"text": "Approved"},
            },
        },
    )
    assert requested.status_code == 201, requested.text
    assert bob.post(f"/api/requests/{requested.json()['id']}/approve").status_code == 200
    assert admin.post("/api/queue/print?printer_id=main").status_code == 202
    worker.tick()
    assert report(bob)["users"] == []
    assert report(alice)["users"][0]["consumed_mm"] > 0
    assert [row["user_id"] for row in report(admin, True)["users"]] == ["alice"]
