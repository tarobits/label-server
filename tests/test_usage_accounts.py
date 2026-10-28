"""Independent account permissions, exact balances and append-only adjustments."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select
from test_access_security import accounts as account_fixture
from test_print_audit import direct, grant, prepare_printer
from test_tape_usage import price, report

from app.models import AuthSession, Role, UsageAdjustment, User

accounts = account_fixture


def permissions(admin, user, *grants):
    with admin.app.state.factory.begin() as session:
        role = session.get(Role, f"{user}-access")
        role.permissions = [{"kind": "application", "permission": grant} for grant in grants]


def adjustment(user="alice", amount=1000, **values):
    return {
        "request_id": str(uuid4()),
        "user_id": user,
        "amount_minor": amount,
        "currency": "EUR",
        "note": "Payment received",
        **values,
    }


def balance(client, user=None):
    response = client.get("/api/usage", params={"user_id": user} if user else {})
    assert response.status_code == 200, response.text
    return response.json()["accounts"][0]["balances"]


def test_permissions_are_independent_immediately_revocable_and_not_printer_grants(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "full")
    for path in ("/api/usage?all_users=true", "/api/usage?user_id=bob", "/api/usage/users"):
        assert alice.get(path).status_code == 403
    assert alice.post("/api/usage/adjustments", json=adjustment()).status_code == 403
    assert balance(alice) == {}
    assert alice.get("/api/usage?user_id=alice").status_code == 200
    permissions(admin, "alice", "usage.view_others")
    assert alice.get("/api/usage?all_users=true").status_code == 200
    assert balance(alice, "bob") == {}
    assert {user["user_id"] for user in alice.get("/api/usage/users").json()} == {
        "alice",
        "bob",
        "administrator",
    }
    assert alice.post("/api/usage/adjustments", json=adjustment()).status_code == 403
    permissions(admin, "bob", "usage.edit_accounts")
    created = bob.post("/api/usage/adjustments", json=adjustment())
    assert created.status_code == 201, created.text
    assert "balances" not in created.json()
    assert created.json()["actor_name"] == "bob"
    assert bob.get("/api/usage/users").status_code == 200
    assert bob.get("/api/usage?user_id=alice").status_code == 403
    assert bob.get("/api/usage?all_users=true").status_code == 403
    assert balance(alice) == {"EUR": "10.000000"}
    assert report(alice)["adjustments"][0]["actor_id"] == "bob"
    assert report(bob)["adjustments"] == []
    permissions(admin, "bob")
    assert bob.post("/api/usage/adjustments", json=adjustment()).status_code == 403
    assert bob.get("/api/usage/users").status_code == 403
    permissions(admin, "alice")
    assert alice.get("/api/usage?user_id=bob").status_code == 403
    assert alice.get("/api/usage?user_id=unknown").status_code == 403
    assert admin.get("/api/usage?user_id=unknown").status_code == 404
    assert admin.get("/api/usage?all_users=true&user_id=alice").status_code == 422


def test_settled_costs_debit_balance_and_payments_do_not_rewrite_print_history(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    price(admin)
    direct(alice, tape, copies=3)
    worker.tick()
    original = report(alice)
    spent = Decimal(original["users"][0]["costs"]["EUR"])
    assert spent > 0
    assert Decimal(balance(alice)["EUR"]) == -spent
    for body in (
        adjustment(amount=500),
        adjustment(amount=-123, note="Correction"),
        adjustment(amount=200, currency="USD"),
    ):
        response = admin.post("/api/usage/adjustments", json=body)
        assert response.status_code == 201, response.text
    result = report(alice)
    assert result["users"] == original["users"]
    assert result["entries"] == original["entries"]
    assert balance(alice) == {"EUR": format(Decimal("3.77") - spent, ".6f"), "USD": "2.000000"}
    assert report(bob)["adjustments"] == []
    assert balance(bob) == {}
    permissions(admin, "bob", "usage.view_others")
    individual = bob.get("/api/usage?user_id=alice").json()
    assert individual == result
    assert all(
        entry["user_id"] == "alice" for entry in individual["entries"] + individual["adjustments"]
    )


def test_pending_and_unpriced_allocations_are_not_charged_until_cost_is_settled(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    direct(alice, tape)
    worker.tick()
    assert report(alice)["users"][0]["unpriced_mm"] > 0
    assert balance(alice) == {}
    price(admin)
    direct(alice, tape)
    worker.backend.fail_after = 0
    worker.tick()
    assert report(alice)["users"][0]["pending_mm"] > 0
    assert balance(alice) == {}
    batch = admin.get("/api/batches").json()[0]
    detail = admin.get(f"/api/batches/{batch['id']}").json()
    reviewed = admin.post(
        f"/api/batches/{batch['id']}/review",
        json={
            "decisions": {item["copy_id"]: "cancelled" for item in detail["items"]},
            "consumed_mm": 100,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert balance(alice) == {"EUR": "-0.250000"}


def test_adjustment_retries_concurrency_and_snapshot_attribution(accounts):
    admin, alice, _ = accounts
    body = adjustment()
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda _: admin.post("/api/usage/adjustments", json=body), range(2))
        )
    assert all(response.status_code == 201 for response in responses)
    assert responses[0].json() == responses[1].json()
    assert balance(alice) == {"EUR": "10.000000"}
    assert (
        admin.post("/api/usage/adjustments", json={**body, "amount_minor": 2000}).status_code == 409
    )
    permissions(admin, "alice", "usage.edit_accounts")
    assert alice.post("/api/usage/adjustments", json=body).status_code == 409
    with admin.app.state.factory.begin() as session:
        session.get(User, "administrator").username = "Renamed operator"
        session.get(User, "alice").username = "Renamed requester"
    saved = admin.post("/api/usage/adjustments", json=body)
    assert saved.json() == responses[0].json()
    assert report(alice)["accounts"][0]["username"] == "Renamed requester"
    assert report(alice)["adjustments"][0]["actor_name"] == "administrator"
    assert report(alice)["adjustments"][0]["username"] == "alice"
    identifier = saved.json()["id"]
    assert admin.delete(f"/api/usage/adjustments/{identifier}").status_code in (404, 405)
    assert admin.put(f"/api/usage/adjustments/{identifier}", json=body).status_code in (404, 405)


@pytest.mark.parametrize(
    "values",
    [
        {"amount_minor": 0},
        {"amount_minor": 1.5},
        {"amount_minor": True},
        {"amount_minor": 1000000001},
        {"amount_minor": -1000000001},
        {"currency": "eur"},
        {"currency": "EURO"},
        {"note": "  "},
        {"note": "x" * 501},
        {"request_id": "invalid"},
        {"actor_id": "forged"},
    ],
)
def test_adjustments_validate_input_without_changing_balance(accounts, values):
    admin, alice, _ = accounts
    assert admin.post("/api/usage/adjustments", json=adjustment(**values)).status_code == 422
    assert balance(alice) == {}


def test_unknown_accounts_and_csrf_are_rejected(accounts):
    admin, alice, _ = accounts
    assert admin.post("/api/usage/adjustments", json=adjustment(user="unknown")).status_code == 404
    assert (
        admin.post(
            "/api/usage/adjustments", json=adjustment(), headers={"X-CSRF-Token": "invalid"}
        ).status_code
        == 403
    )
    assert balance(alice) == {}


def test_totals_include_all_adjustments_and_survive_purged_users_and_restart(accounts):
    admin, alice, _ = accounts
    for _ in range(102):
        assert admin.post("/api/usage/adjustments", json=adjustment(amount=1)).status_code == 201
    assert len(report(alice)["adjustments"]) == 100
    assert balance(alice) == {"EUR": "1.020000"}
    with admin.app.state.factory.begin() as session:
        session.execute(delete(AuthSession).where(AuthSession.user_id == "alice"))
        session.delete(session.get(User, "alice"))
    assert balance(admin, "alice") == {"EUR": "1.020000"}
    assert admin.post("/api/usage/adjustments", json=adjustment(amount=-2)).status_code == 201
    config = Config("alembic.ini")
    config.attributes["database_url"] = admin.app.state.settings.database_url
    command.upgrade(config, "head")
    command.check(config)
    with admin.app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(UsageAdjustment)) == 103
    assert balance(admin, "alice") == {"EUR": "1.000000"}


def test_both_permissions_are_assignable_through_role_confirmation(accounts):
    admin, _, _ = accounts
    grants = ["usage.view_others", "usage.edit_accounts"]
    assert set(grants).issubset(
        {entry["id"] for entry in admin.get("/api/admin/permissions").json()}
    )
    body = {
        "name": "Accounts",
        "permissions": [{"kind": "application", "permission": permission} for permission in grants],
    }
    preview = admin.post(
        "/api/admin/access-preview", json={"resource": "roles", "method": "POST", "payload": body}
    )
    assert preview.status_code == 200, preview.text
    result = admin.post(
        "/api/admin/roles",
        json=body,
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert result.status_code == 201, result.text
    assert result.json()["permissions"] == body["permissions"]
