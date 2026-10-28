"""Quotes use the same physical consumption and price arithmetic as settled usage."""

from decimal import Decimal

import pytest
from conftest import install, profile
from sqlalchemy import func, select
from test_access_security import accounts as account_fixture
from test_cut_planning import configure_brother, short_document
from test_fleet import device, fit, group
from test_print_audit import grant

from app.models import Batch, Cartridge, PrintJob, Role, TapeAllocation

accounts = account_fixture


def set_price(client, cartridge, value=2000, currency="EUR"):
    response = client.put(
        f"/api/cartridges/{cartridge['id']}/price",
        json={"price_minor": value, "currency": currency},
    )
    assert response.status_code == 200, response.text


def preview(client, tape, copies=1, **extra):
    response = client.post(
        "/api/preview",
        json={
            "template_id": "text",
            "tape_profile": tape["id"],
            "copies": copies,
            "data": {"text": "Test"},
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def quote(record):
    return Decimal(record["cost_estimate"]["quotes"][0]["minimum"])


@pytest.mark.parametrize("strip", [True, False])
def test_short_label_copies_include_feed_minimum_padding_and_one_leader_without_charging(
    client, strip
):
    worker, backend = configure_brother(client)
    backend.production.cut_each = not strip
    tape = profile(client, threshold=1000, width=12)
    cartridge = install(client, tape["id"])
    set_price(client, cartridge)
    template = client.post(
        "/api/templates", json={"name": "Tiny", "document": short_document()}
    ).json()
    for copies in (1, 3):
        result = preview(client, tape, copies, template_id=template["id"])
        plan = result["print_plan"]
        label = plan["label_output"][0]
        if strip:
            expected_mm = 24.5 + max(24.5, copies * label["output_length_mm"])
        else:
            expected_mm = 24.5 + copies * 24.5
        expected = (Decimal(str(expected_mm)) * 20 / 8000).quantize(Decimal("0.000001"))
        assert quote(result) == expected
        assert result["cost_estimate"]["basis"] == "installed"
    with client.app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Batch)) == 0
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 0
        assert session.scalar(select(func.count()).select_from(TapeAllocation)) == 0
        assert session.get(Cartridge, cartridge["id"]).remaining_mm == 8000


def test_unpriced_missing_and_inventory_fallback_are_explicit_and_free_is_zero(client):
    tape = profile(client)
    assert preview(client, tape)["cost_estimate"]["reason"] == "cartridge"
    cartridge = install(client, tape["id"])
    assert preview(client, tape)["cost_estimate"]["reason"] == "price"
    set_price(client, cartridge, 0)
    assert quote(preview(client, tape)) == 0
    set_price(client, cartridge)
    assert client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 200
    result = preview(client, tape)
    assert result["cost_estimate"]["basis"] == "inventory"
    assert quote(result) > 0
    other = profile(client, name="Other colour")
    wrong_tape = install(client, other["id"])
    set_price(client, wrong_tape, 999999)
    assert quote(preview(client, tape)) == quote(result)


def test_group_quotes_ranges_currencies_and_unpriced_members_without_leaking_printer_identity(
    accounts,
):
    admin, alice, _ = accounts
    tape = profile(admin)
    first = install(admin, tape["id"])
    second = device(admin, name="Hidden printer identity")
    last = fit(admin, second, tape)
    dest = group(admin, ["main", second])
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": dest, "level": "request"}
        ]
    set_price(admin, first, 1000)
    set_price(admin, last, 2000)
    result = preview(alice, tape, destination_id=dest)
    quotes = result["cost_estimate"]["quotes"]
    assert len(quotes) == 1
    assert Decimal(quotes[0]["maximum"]) == Decimal(quotes[0]["minimum"]) * 2
    assert "Hidden printer identity" not in str(result["cost_estimate"])
    assert second not in str(result["cost_estimate"])
    set_price(admin, last, 2000, "USD")
    assert {
        row["currency"]
        for row in preview(alice, tape, destination_id=dest)["cost_estimate"]["quotes"]
    } == {"EUR", "USD"}
    set_price(admin, last, None)
    assert preview(alice, tape, destination_id=dest)["cost_estimate"]["incomplete"] is True
    assert alice.get(f"/api/status?printer_id={second}").status_code == 403
    assert (
        alice.post(
            "/api/preview",
            json={"template_id": "text", "tape_profile": tape["id"], "destination_id": second},
        ).status_code
        == 403
    )


def test_queue_requotes_remaining_copies_and_current_prices_for_requester(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "print")
    tape = profile(admin, threshold=1000)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    submitted = alice.post(
        "/api/jobs",
        json={
            "destination_id": "main",
            "tape_profile": tape["id"],
            "copies": 3,
            "data": {"text": "Test"},
        },
    )
    assert submitted.status_code == 201, submitted.text
    saved = submitted.json()
    full = alice.get("/api/queue/groups?copy_state=queued").json()[0]
    assert quote(full) == quote(preview(alice, tape, 3))
    cancelled = alice.post("/api/queue/remove", json={"copy_ids": [saved["labels"][0]["id"]]})
    assert cancelled.status_code == 200, cancelled.text
    remaining = alice.get("/api/queue/groups?copy_state=queued").json()[0]
    assert quote(remaining) == quote(preview(alice, tape, 2))
    assert quote(remaining) < quote(full)
    set_price(admin, cartridge, 4000)
    assert quote(alice.get("/api/queue/groups?copy_state=queued").json()[0]) == 2 * quote(remaining)


def test_csv_draft_quote_precedes_submission_reprices_without_changing_saved_geometry(client):
    from test_runs import run_body

    body = run_body(client)
    cartridge = install(client, body["tape_profile"])
    set_price(client, cartridge)
    prepared = client.post("/api/runs/prepare", json=body)
    assert prepared.status_code == 200, prepared.text
    run = prepared.json()["run"]
    assert run["copies"] > 1
    assert quote(run) == (Decimal(str(run["estimated_mm"])) * 20 / 8000).quantize(
        Decimal("0.000001")
    )
    set_price(client, cartridge, 4000)
    refreshed = client.get(f"/api/runs/{run['id']}").json()
    assert quote(refreshed) == 2 * quote(run)
    assert refreshed["print_plan"] == run["print_plan"]
    submitted = client.post(f"/api/runs/{run['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    queued = client.get("/api/queue/groups?copy_state=queued").json()[0]
    assert quote(queued) == quote(refreshed)


def test_quote_input_validation_does_not_bypass_preview_access(client):
    tape = profile(client)
    for copies in (0, 1001):
        assert (
            client.post(
                "/api/preview",
                json={"template_id": "text", "copies": copies, "tape_profile": tape["id"]},
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/preview",
            json={"template_id": "text", "tape_profile": "missing", "data": {"text": "Test"}},
        ).status_code
        == 404
    )
    narrow = profile(client, width=12)
    assert (
        client.post(
            "/api/preview", json={"template_id": "text", "tape_profile": narrow["id"]}
        ).status_code
        == 422
    )
