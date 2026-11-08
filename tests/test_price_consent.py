from decimal import Decimal

from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_cost_estimates import preview, set_price
from test_granular_printer_permissions import set_permissions

from app.models import Notification, TapeAllocation, UnitCharge
from app.printer.base import PrintResult


def submission(tape, quote, copies=1, maximum=None):
    return {
        "destination_id": "main",
        "tape_profile": tape["id"],
        "data": {"text": "Test"},
        "copies": copies,
        "quote_id": quote["quote_id"],
        "maximum_price": maximum,
    }


def test_quote_bound_to_requester_geometry_and_quantity(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    for user in ("alice", "bob"):
        set_permissions(admin, user, "view", "submit_directly")
    quote = preview(alice, tape)["cost_estimate"]
    body = submission(tape, quote)
    assert bob.post("/api/jobs", json=body).status_code == 409
    assert alice.post("/api/jobs", json={**body, "copies": 2}).status_code == 409
    response = alice.post("/api/jobs", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["template_snapshot"]["pricing"]["quotes"]["EUR"] > 0
    assert (
        alice.put(
            f"/api/jobs/{response.json()['id']}/copies", json={"copies": 2, "expected_copies": 1}
        ).status_code
        == 409
    )


def test_maximum_waits_notifies_once_and_prints_when_affordable(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    set_permissions(admin, "alice", "view", "submit_directly", "start_own")
    quote = preview(alice, tape)["cost_estimate"]
    response = alice.post(
        "/api/jobs", json=submission(tape, quote, maximum={"currency": "EUR", "micros": 1000})
    )
    assert response.status_code == 201, response.text
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    worker.tick()
    assert worker.backend.batches == []
    with admin.app.state.factory() as session:
        notices = list(
            session.scalars(
                select(Notification).where(
                    Notification.recipient_id == "alice",
                    Notification.title == "No cartridge meets your maximum",
                )
            )
        )
        assert len(notices) == 1
    assert alice.post("/api/queue/print").status_code == 409
    set_price(admin, cartridge, 1)
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert Decimal(alice.get("/api/accounts").json()["charges"][0]["charged"]) <= Decimal("0.001")


def test_unexpected_consumption_cannot_exceed_maximum_and_owner_is_notified(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    set_permissions(admin, "alice", "view", "submit_directly")
    quote = preview(alice, tape)["cost_estimate"]
    maximum = int(Decimal(quote["quotes"][0]["maximum"]) * 1000000)
    response = alice.post(
        "/api/jobs", json=submission(tape, quote, maximum={"currency": "EUR", "micros": maximum})
    )
    assert response.status_code == 201, response.text
    worker = admin.app.state.fleet.workers["main"]
    worker.backend.print_batch = lambda labels: PrintResult(
        worker.backend.estimate_consumption(labels) * 2
    )
    worker.tick()
    with admin.app.state.factory() as session:
        row = session.scalar(select(TapeAllocation))
        unit = session.scalar(select(UnitCharge))
        assert int(row.charged_micros) == maximum < int(row.cost_micros)
        assert unit.charged_micros == row.charged_micros
        assert session.scalar(
            select(Notification).where(
                Notification.title == "Cartridge cost reduction",
                Notification.recipient_id == "administrator",
            )
        )


def test_inventory_price_episodes_continue_without_installed_tape_and_while_held(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=100)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    set_permissions(admin, "alice", "view", "submit_directly")
    quote = preview(alice, tape)["cost_estimate"]
    assert (
        alice.post(
            "/api/jobs", json=submission(tape, quote, maximum={"currency": "EUR", "micros": 1000})
        ).status_code
        == 201
    )
    with admin.app.state.factory.begin() as session:
        from app.destinations import printer_state

        state = printer_state(session, "main")
        state.active_cartridge_id = None
        state.automatic_printing_held = True
    worker = admin.app.state.fleet.workers["main"]

    def notices():
        with admin.app.state.factory() as session:
            return len(
                list(
                    session.scalars(
                        select(Notification).where(
                            Notification.title == "No cartridge meets your maximum",
                            Notification.recipient_id == "alice",
                        )
                    )
                )
            )

    worker.tick()
    worker.tick()
    assert notices() == 1
    set_price(admin, cartridge, 1)
    worker.tick()
    assert notices() == 1  # Affordable inventory exists, even though nothing is installed.
    set_price(admin, cartridge, 2000)
    worker.tick()
    worker.tick()
    assert notices() == 2
    assert not worker.backend.batches
