"""Cartridge-scoped usage without altering account balances or user boundaries."""

from conftest import profile
from test_access_security import accounts as account_fixture
from test_usage_accounts import adjustment, permissions

from app.models import Batch, Cartridge, State, TapeAllocation

accounts = account_fixture


def seed_usage(admin):
    tape = profile(admin)
    with admin.app.state.factory.begin() as session:
        for identifier in ("a", "b", "private"):
            session.add(
                Cartridge(
                    id=identifier,
                    name=f"Cartridge {identifier}",
                    profile_id=tape["id"],
                    nominal_length_mm=8000,
                    remaining_mm=4000,
                )
            )
        session.flush()
        allocations = [(f"old-{i:03}", "a", "alice", 10, "25000", 1000 + i) for i in range(110)]
        allocations += [
            ("paid", "b", "alice", 100, "250000", 2000),
            ("pending", "b", "alice", None, None, 2001),
            ("unpriced", "b", "alice", 20, None, 2002),
            ("other", "private", "bob", 200, "500000", 2003),
        ]
        for identifier, cartridge, user, consumed, cost, stamp in allocations:
            session.add(
                Batch(
                    id=identifier,
                    cartridge_id=cartridge,
                    printer_id="main",
                    created_at=stamp,
                    estimated_mm=30,
                    consumed_mm=consumed,
                    state=State.NEEDS_REVIEW if consumed is None else State.PRINTED,
                    consumption_source=None if consumed is None else "measured",
                )
            )
            session.flush()
            session.add(
                TapeAllocation(
                    batch_id=identifier,
                    user_id=user,
                    username=user,
                    planned_mm=30,
                    consumed_mm=consumed,
                    cost_micros=cost,
                    nominal_length_mm=8000,
                    price_minor=2000 if cost else None,
                    currency="EUR",
                )
            )
    assert admin.post("/api/usage/adjustments", json=adjustment(amount=100)).status_code == 201


def test_cartridge_filter_applies_before_recent_limit_and_conserves_balances(accounts):
    admin, alice, _ = accounts
    seed_usage(admin)
    full = alice.get("/api/usage").json()
    assert full["accounts"][0]["balances"] == {"EUR": "-2.000000"}
    assert {item["id"] for item in full["cartridges"]} == {"a", "b"}
    assert full["entries"][0]["cartridge_name"] == "Cartridge b"
    assert full["entries"][0]["profile_name"] == "White"
    for cartridge in ("a", "b", "unknown", "private"):
        filtered = alice.get("/api/usage", params={"cartridge_id": cartridge}).json()
        assert filtered["accounts"] == full["accounts"]
        assert filtered["adjustments"] == full["adjustments"]
        assert filtered["cartridges"] == full["cartridges"]
        assert all(row["cartridge_id"] == cartridge for row in filtered["entries"])
        if cartridge == "a":
            assert len(filtered["entries"]) == 100
            assert filtered["users"][0]["costs"] == {"EUR": "2.750000"}
            assert filtered["users"][0]["consumed_mm"] == 1100
        elif cartridge == "b":
            assert len(filtered["entries"]) == 3
            summary = filtered["users"][0]
            assert summary["consumed_mm"] == 120
            assert summary["pending_mm"] == 30
            assert summary["unpriced_mm"] == 20
            assert summary["costs"] == {"EUR": "0.250000"}
        else:
            assert filtered["users"] == [] and filtered["entries"] == []


def test_cartridge_filter_and_options_obey_usage_permissions(accounts):
    admin, alice, bob = accounts
    seed_usage(admin)
    for params in ({"user_id": "bob"}, {"all_users": "true"}):
        assert (
            alice.get("/api/usage", params={**params, "cartridge_id": "private"}).status_code == 403
        )
    permissions(admin, "alice", "usage.view_others")
    all_users = alice.get("/api/usage?all_users=true&cartridge_id=private").json()
    assert [row["user_id"] for row in all_users["users"]] == ["bob"]
    assert {item["id"] for item in all_users["cartridges"]} == {"a", "b", "private"}
    individual = alice.get("/api/usage?user_id=bob&cartridge_id=private").json()
    assert individual == bob.get("/api/usage?cartridge_id=private").json()
    assert [item["id"] for item in individual["cartridges"]] == ["private"]
    assert admin.get("/api/usage?cartridge_id=").status_code == 422
