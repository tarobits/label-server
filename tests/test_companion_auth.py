import json

from sqlalchemy import delete, select
from test_access_security import accounts as accounts

from app.auth import hash_password
from app.models import Companion, CompanionPin, CompanionSession, Location, ResourceGrant, User


def station(admin, *, bound=None):
    with admin.app.state.factory.begin() as session:
        if not session.get(Location, "workshop"):
            session.add(Location(id="workshop", name="Workshop"))
    body = {
        "name": "Workshop station",
        "location_id": "workshop",
        "bound_user_id": bound,
        "grants": [
            {"principal_kind": "user", "principal_id": "alice", "permission": "companion.access"}
        ],
    }
    response = admin.post("/api/companions", json=body)
    assert response.status_code == 201, response.text
    item = response.json()
    return item, {"Authorization": f"Bearer {item['api_key']}"}, body


def test_only_admin_can_bind_station_and_key_cannot_impersonate_another_user(accounts):
    admin, alice, bob = accounts
    item, headers, body = station(admin, bound="alice")
    assert alice.post("/api/companions", json=body).status_code == 403
    assert bob.get("/api/companions").status_code == 403
    assert (
        admin.post(
            "/api/companion/unlock", headers=headers, json={"user_id": "administrator"}
        ).status_code
        == 403
    )
    unlocked = admin.post("/api/companion/unlock", headers=headers, json={"user_id": "alice"})
    assert unlocked.status_code == 200, unlocked.text
    session_headers = {**headers, "X-Companion-Session": unlocked.json()["session_token"]}
    assert item["api_key"] not in admin.get("/api/companions").text
    assert "key_hash" not in admin.get("/api/companions").text
    with admin.app.state.factory() as session:
        assert session.get(Companion, item["id"]).key_hash != item["api_key"]
        assert (
            session.scalar(select(CompanionSession)).token_hash != unlocked.json()["session_token"]
        )
    # Live removal of companion access invalidates an already unlocked session.
    with admin.app.state.factory.begin() as session:
        session.execute(delete(ResourceGrant).where(ResourceGrant.scope_kind == "companion"))
    assert admin.post("/api/companion/lock", headers=session_headers).status_code == 403


def test_user_pins_are_personal_rate_limited_and_reset_revokes_station_sessions(accounts):
    admin, alice, _ = accounts
    _, headers, _ = station(admin)
    with admin.app.state.factory.begin() as session:
        session.get(User, "alice").password_hash = hash_password("example test password")
    body = {"current_password": "example test password", "pin": "123456"}
    assert alice.put("/api/companions/account/pin", json=body).status_code == 200
    response = admin.get("/api/companion/users", headers=headers)
    assert response.json()["users"] == [{"id": "alice", "username": "alice"}]
    unlocked = admin.post(
        "/api/companion/unlock", headers=headers, json={"user_id": "alice", "pin": "123456"}
    )
    assert unlocked.status_code == 200, unlocked.text
    assert (
        alice.put("/api/companions/account/pin", json={**body, "pin": "654321"}).status_code == 200
    )
    assert (
        admin.post(
            "/api/companion/lock",
            headers={**headers, "X-Companion-Session": unlocked.json()["session_token"]},
        ).status_code
        == 401
    )
    statuses = [
        admin.post(
            "/api/companion/unlock", headers=headers, json={"user_id": "alice", "pin": "111111"}
        ).status_code
        for _ in range(11)
    ]
    assert statuses[-1] == 429
    audit = admin.get("/api/audit").text
    assert "123456" not in audit and "654321" not in audit and "example test password" not in audit
    assert "account.pin_changed" in audit
    with admin.app.state.factory() as session:
        assert session.get(CompanionPin, "alice").pin_hash not in audit


def test_station_key_rotation_binding_changes_and_sessions_are_isolated(accounts):
    admin, _, _ = accounts
    first, headers, body = station(admin, bound="alice")
    second, other_headers, _ = station(admin, bound="alice")
    token = admin.post("/api/companion/unlock", headers=headers, json={"user_id": "alice"}).json()[
        "session_token"
    ]
    assert (
        admin.post(
            "/api/companion/lock", headers={**other_headers, "X-Companion-Session": token}
        ).status_code
        == 401
    )
    updated = {**body, "bound_user_id": None, "expected_revision": first["revision"]}
    preview = admin.post(f"/api/companions/{first['id']}/preview", json=updated)
    assert preview.status_code == 200, preview.text
    response = admin.put(
        f"/api/companions/{first['id']}",
        json=updated,
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert response.status_code == 200, response.text
    assert (
        admin.post(
            "/api/companion/lock", headers={**headers, "X-Companion-Session": token}
        ).status_code
        == 401
    )
    new_key = admin.post(f"/api/companions/{first['id']}/key").json()["api_key"]
    assert admin.get("/api/companion/users", headers=headers).status_code == 401
    assert (
        admin.get(
            "/api/companion/users", headers={"Authorization": f"Bearer {new_key}"}
        ).status_code
        == 200
    )
    assert admin.delete(f"/api/companions/{second['id']}/key").status_code == 200
    assert admin.get("/api/companion/users", headers=other_headers).status_code == 401
    assert new_key not in json.dumps(admin.get("/api/audit").json())
