"""Manual review corrects historical accounting without changing installed media."""

import pytest
from conftest import install, job, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_print_audit import grant

from app.models import Batch, Cartridge, PrinterState, State, TapeAllocation

accounts = account_fixture


def spare(client, tape, **values):
    response = client.post(
        "/api/cartridges",
        json={
            "name": "Previous cartridge",
            "profile_id": tape["id"],
            "nominal_length_mm": 4000,
            **values,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def interrupted(client, tape):
    queued = job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    assert batch["state"] == "needs_review"
    return batch, {"decisions": {queued["labels"][0]["id"]: "cancelled"}, "consumed_mm": 100}


@pytest.mark.parametrize("selection", ["default", "original", "corrected"])
def test_review_defaults_to_print_start_and_only_charges_selected_cartridge(client, selection):
    tape = profile(client, threshold=1)
    original = install(client, tape["id"])
    response = client.put(f"/api/cartridges/{original['id']}/price", json={"price_minor": 2000})
    assert response.status_code == 200
    corrected = spare(client, tape, price_minor=1200, currency="GBP")
    current = spare(client, tape, name="Currently installed", remaining_mm=0)
    batch, body = interrupted(client, tape)
    confirmation = {"cartridge_id": current["id"], "fingerprint": "current-tape"}
    # Simulate a later physical assignment; the historical batch still points at
    # its print-start cartridge, independent of today's installed state.
    with client.app.state.factory.begin() as session:
        state = session.scalar(select(PrinterState))
        state.active_cartridge_id = current["id"]
        state.media_confirmation = confirmation
        state.media_verified_fingerprint = "current-verification"
        state.cartridge_check_pending = True
        state.empty_alert_cartridge_id = current["id"]
        # Even an explicit choice of the original must retain its frozen price.
        session.get(Cartridge, original["id"]).price_minor = 9999
    selected = corrected if selection == "corrected" else original
    if selection != "default":
        body["cartridge_id"] = selected["id"]
    path = f"/api/batches/{batch['id']}/review"
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["cartridge_id"] == selected["id"]
    assert response.json()["print_plan"] == batch["print_plan"]
    assert client.post(path, json=body).status_code == 409
    with client.app.state.factory() as session:
        state = session.scalar(select(PrinterState))
        assert state.active_cartridge_id == current["id"]
        assert state.media_confirmation == confirmation
        assert state.media_verified_fingerprint == "current-verification"
        assert state.cartridge_check_pending
        assert state.cartridge_check_enabled
        assert state.empty_alert_cartridge_id == current["id"]
        for cartridge in (original, corrected, current):
            stored = session.get(Cartridge, cartridge["id"])
            expected = cartridge["remaining_mm"] - (100 if cartridge["id"] == selected["id"] else 0)
            assert stored.remaining_mm == expected
            assert not stored.consumption_uncertain
        allocation = session.scalar(
            select(TapeAllocation).where(TapeAllocation.batch_id == batch["id"])
        )
        assert allocation.consumed_mm == 100
        assert allocation.price_minor == (1200 if selection == "corrected" else 2000)
        assert allocation.nominal_length_mm == (4000 if selection == "corrected" else 8000)
        assert allocation.currency == ("GBP" if selection == "corrected" else "EUR")
        assert allocation.cost_micros == ("300000" if selection == "corrected" else "250000")


def test_invalid_cartridge_or_decisions_leave_review_and_tape_untouched(client):
    tape = profile(client, threshold=1)
    original = install(client, tape["id"])
    alternative = spare(client, tape)
    batch, body = interrupted(client, tape)
    path = f"/api/batches/{batch['id']}/review"
    for invalid, code in [
        ({**body, "cartridge_id": "missing"}, 404),
        ({**body, "cartridge_id": ""}, 422),
        ({**body, "cartridge_id": alternative["id"], "decisions": {}}, 409),
    ]:
        assert client.post(path, json=invalid).status_code == code
    with client.app.state.factory() as session:
        stored = session.get(Batch, batch["id"])
        assert stored.cartridge_id == original["id"]
        assert stored.state == State.NEEDS_REVIEW
        assert session.get(Cartridge, original["id"]).remaining_mm == 8000
        assert session.get(Cartridge, original["id"]).consumption_uncertain
        assert session.get(Cartridge, alternative["id"]).remaining_mm == 4000
        assert session.scalar(select(TapeAllocation)).consumed_mm is None


@pytest.mark.parametrize("other_on", ["original", "corrected"])
def test_review_preserves_other_unresolved_attempts(client, other_on):
    tape = profile(client, threshold=1)
    original = install(client, tape["id"])
    corrected = spare(client, tape)
    batch, body = interrupted(client, tape)
    other = original if other_on == "original" else corrected
    with client.app.state.factory.begin() as session:
        session.add(
            Batch(
                id="other-attempt",
                printer_id="elsewhere",
                cartridge_id=other["id"],
                state=State.NEEDS_REVIEW,
                estimated_mm=50,
            )
        )
        session.get(Cartridge, other["id"]).consumption_uncertain = True
    response = client.post(
        f"/api/batches/{batch['id']}/review", json={**body, "cartridge_id": corrected["id"]}
    )
    assert response.status_code == 200, response.text
    with client.app.state.factory() as session:
        assert session.get(Batch, "other-attempt").state == State.NEEDS_REVIEW
        assert session.get(Cartridge, other["id"]).consumption_uncertain
        assert session.get(Cartridge, corrected["id"]).remaining_mm == 3900


def test_review_cartridge_correction_requires_review_permission_not_install_permission(accounts):
    admin, moderator, ordinary = accounts
    grant(admin, "alice", "moderator")
    grant(admin, "bob", "print")
    tape = profile(admin, threshold=1)
    original = install(admin, tape["id"])
    corrected = spare(admin, tape)
    batch, body = interrupted(admin, tape)
    path = f"/api/batches/{batch['id']}/review"
    body["cartridge_id"] = corrected["id"]
    assert ordinary.post(path, json=body).status_code == 403
    assert (
        moderator.put(
            "/api/printer/active-tape", json={"cartridge_id": corrected["id"]}
        ).status_code
        == 403
    )
    response = moderator.post(path, json=body)
    assert response.status_code == 200, response.text
    assert admin.get("/api/status").json()["active_cartridge_id"] == original["id"]
    assert admin.get(f"/api/batches/{batch['id']}").json()["cartridge_id"] == corrected["id"]
