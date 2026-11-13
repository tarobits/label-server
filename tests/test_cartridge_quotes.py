from copy import deepcopy

from sqlalchemy import delete, select
from test_access_security import accounts as accounts
from test_cost_estimates import set_price
from test_use_overrides import prepared

from app.i18n import notice_text
from app.models import CartridgeQuoteOffer, Notification, PrintJob, ResourceGrant, UnitCharge


def without_quote(accounts):
    admin, _, _ = accounts
    cartridge, _, job = prepared(accounts)
    with admin.app.state.factory.begin() as session:
        stored = session.get(PrintJob, job["id"])
        stored.template_snapshot = {**stored.template_snapshot, "pricing": {}}
    return cartridge, job


def propose(admin, cartridge, job):
    body = {"printer_id": "main", "cartridge_id": cartridge["id"], "job_ids": [job["id"]]}
    response = admin.post("/api/cartridge-quotes", json=body)
    assert response.status_code == 201, response.text
    assert admin.post("/api/cartridge-quotes", json=body).json() == response.json()
    return response.json()["offer_ids"][0]


def accept(alice, identifier):
    response = alice.get(f"/api/cartridge-quotes/{identifier}")
    assert response.status_code == 200, response.text
    quote = response.json()["quote"]
    body = {
        "quote_hash": quote["quote_hash"],
        "maximum_price": {"currency": quote["currency"], "micros": quote["amount_micros"]},
    }
    response = alice.post(f"/api/cartridge-quotes/{identifier}/accept", json=body)
    assert response.status_code == 200, response.text
    assert (
        alice.post(f"/api/cartridge-quotes/{identifier}/accept", json=body).json()
        == response.json()
    )
    return body


def test_missing_quote_notifies_requester_but_never_grants_use_or_starts_printing(accounts):
    admin, alice, bob = accounts
    cartridge, job = without_quote(accounts)
    detail = admin.post("/api/queue/print").json()["detail"]
    assert detail["code"] == "cartridge_quote_required" and detail["job_ids"] == [job["id"]]
    identifier = propose(admin, cartridge, job)
    assert bob.get(f"/api/cartridge-quotes/{identifier}").status_code == 404
    assert admin.get(f"/api/cartridge-quotes/{identifier}").status_code == 404
    assert (
        admin.post(
            f"/api/cartridge-quotes/{identifier}/accept",
            json={"quote_hash": "a" * 64, "maximum_price": {"currency": "EUR", "micros": 1}},
        ).status_code
        == 404
    )
    with admin.app.state.factory() as session:
        notices = list(
            session.scalars(
                select(Notification).where(
                    Notification.title == "Printing needs your price approval"
                )
            )
        )
        assert len(notices) == 1 and notices[0].recipient_id == "alice"
        assert notice_text(notices[0], "title", "de") == "Druck benötigt deine Preisfreigabe"
        assert notice_text(notices[0], "message", "de") == (
            "Eine Bedienperson hat eine andere Kassette für deine wartenden Etiketten vorgeschlagen. "
            "Prüfe den Preis vor dem Druck."
        )
    accepted = accept(alice, identifier)
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    assert not worker.backend.batches
    detail = admin.post("/api/queue/print").json()["detail"]
    assert detail["code"] == "cartridge_use"
    ids = [row["copy_id"] for row in detail["items"]]
    response = admin.post(
        "/api/queue/print",
        json={
            "copy_ids": ids,
            "approve_copy_ids": ids,
            "use_confirmations": detail["confirmations"],
        },
    )
    assert response.status_code == 202, response.text
    worker.tick()
    assert len(worker.backend.batches) == 1
    with admin.app.state.factory() as session:
        charges = list(session.scalars(select(UnitCharge).where(UnitCharge.job_id == job["id"])))
        assert (
            sum(int(charge.charged_micros) for charge in charges)
            <= accepted["maximum_price"]["micros"]
        )
        assert not list(
            session.scalars(select(ResourceGrant).where(ResourceGrant.scope_id == cartridge["id"]))
        )
    audit = admin.get("/api/audit").json()
    assert "price.accepted" in str(audit)


def test_quote_detects_price_changes_and_decline_does_not_change_saved_consent(accounts):
    admin, alice, _ = accounts
    cartridge, job = without_quote(accounts)
    identifier = propose(admin, cartridge, job)
    quote = alice.get(f"/api/cartridge-quotes/{identifier}").json()["quote"]
    body = {
        "quote_hash": quote["quote_hash"],
        "maximum_price": {"currency": quote["currency"], "micros": quote["amount_micros"]},
    }
    set_price(admin, cartridge, 6000)
    stale = alice.post(
        f"/api/cartridge-quotes/{identifier}/accept", json=body, headers={"Accept-Language": "de"}
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == (
        "Der Preis oder die eingereihten Kopien haben sich geändert. Aktualisiere das Angebot."
    )
    assert alice.post(f"/api/cartridge-quotes/{identifier}/decline").status_code == 200
    assert alice.post(f"/api/cartridge-quotes/{identifier}/decline").status_code == 200
    assert alice.post(f"/api/cartridge-quotes/{identifier}/accept", json=body).status_code == 409
    with admin.app.state.factory() as session:
        assert session.get(PrintJob, job["id"]).template_snapshot["pricing"] == {}
        assert session.get(CartridgeQuoteOffer, identifier).status == "declined"


def test_new_currency_requires_explicit_acceptance_and_preserves_old_charges(accounts):
    admin, alice, _ = accounts
    cartridge, _, job = prepared(accounts)
    detail = admin.post("/api/queue/print").json()["detail"]
    first = detail["items"][0]["copy_id"]
    assert (
        admin.post(
            "/api/queue/print",
            json={
                "copy_ids": [first],
                "approve_copy_ids": [first],
                "use_confirmations": detail["confirmations"],
            },
        ).status_code
        == 202
    )
    admin.app.state.fleet.workers["main"].tick()
    with admin.app.state.factory.begin() as session:
        stored = session.get(PrintJob, job["id"])
        original = deepcopy(stored.template_snapshot["pricing"])
        previous_charge = session.scalar(select(UnitCharge).where(UnitCharge.job_id == job["id"]))
        previous_amount = previous_charge.charged_micros
        assert int(previous_amount) > 0
    set_price(admin, cartridge, 5000, "USD")
    identifier = propose(admin, cartridge, job)
    accepted = accept(alice, identifier)
    assert accepted["maximum_price"]["currency"] == "USD"
    with admin.app.state.factory() as session:
        pricing = session.get(PrintJob, job["id"]).template_snapshot["pricing"]
        assert pricing["quotes"]["EUR"] == original["quotes"]["EUR"]
        assert pricing["maximum"]["currency"] == "USD"
        assert (
            session.scalar(select(UnitCharge).where(UnitCharge.job_id == job["id"])).charged_micros
            == previous_amount
        )
        assert (
            len(session.get(CartridgeQuoteOffer, identifier).acceptance["quote"]["copy_ids"]) == 1
        )
        assert (
            session.get(CartridgeQuoteOffer, identifier).acceptance["quote"]["previous_pricing"]
            == original
        )


def test_revoked_operator_cannot_obtain_fresh_requester_consent(accounts):
    from test_granular_printer_permissions import set_permissions

    admin, alice, bob = accounts
    cartridge, job = without_quote(accounts)
    set_permissions(admin, "bob", "view", "view_queue", "start_any")
    with admin.app.state.factory.begin() as session:
        session.add(
            ResourceGrant(
                principal_kind="user",
                principal_id="bob",
                scope_kind="cartridge",
                scope_id=cartridge["id"],
                permission="cartridge.approve_use",
            )
        )
    identifier = propose(bob, cartridge, job)
    quote = alice.get(f"/api/cartridge-quotes/{identifier}").json()["quote"]
    body = {
        "quote_hash": quote["quote_hash"],
        "maximum_price": {"currency": quote["currency"], "micros": quote["amount_micros"]},
    }
    with admin.app.state.factory.begin() as session:
        session.execute(delete(ResourceGrant).where(ResourceGrant.principal_id == "bob"))
    response = alice.get(
        f"/api/cartridge-quotes/{identifier}", headers={"Accept-Language": "de"}
    ).json()
    assert response["quote"] is None
    assert (
        response["unavailable"]
        == "Die Kassettenberechtigung der Bedienperson ist nicht mehr gültig."
    )
    assert alice.post(f"/api/cartridge-quotes/{identifier}/accept", json=body).status_code == 409
    assert alice.post(f"/api/cartridge-quotes/{identifier}/decline").status_code == 200
