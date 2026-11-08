from test_access_security import accounts as accounts

from app.models import Notification
from app.notifications import enqueue


def test_private_inbox_survives_absent_delivery_and_read_state_is_per_user(accounts):
    admin, alice, bob = accounts
    with admin.app.state.factory.begin() as session:
        enqueue(
            session,
            "Printed",
            "Your labels are ready",
            "/#/activity",
            recipient_id="alice",
            kind="job_printed",
        )
        enqueue(session, "Private", "Bob only", "/#/jobs", recipient_id="bob")
    inbox = alice.get("/api/inbox").json()
    assert inbox["total"] == inbox["unread"] == 1
    notice = inbox["items"][0]
    assert notice["title"] == "Printed"
    assert set(notice) == {"id", "title", "message", "path", "kind", "created_at", "read_at"}
    assert bob.put(f"/api/inbox/{notice['id']}/read", json={"read": True}).status_code == 404
    assert alice.put(f"/api/inbox/{notice['id']}/read", json={"read": True}).status_code == 204
    assert alice.get("/api/inbox?unread_only=true").json()["total"] == 0
    assert alice.put(f"/api/inbox/{notice['id']}/read", json={"read": False}).status_code == 204
    assert alice.get("/api/inbox").json()["unread"] == 1
    assert admin.get("/api/inbox").json()["total"] == 0


def test_pagination_filters_and_mark_all_do_not_cross_recipients(accounts):
    admin, alice, bob = accounts
    with admin.app.state.factory.begin() as session:
        for index in range(23):
            enqueue(session, str(index), "Notice", "/#/jobs", now=index, recipient_id="alice")
        enqueue(session, "Admin", "Administrative notice", "/#/", recipient_id="administrators")
        session.add(
            Notification(
                title="Bob",
                message="Private",
                path="https://example.com",
                recipient_id="bob",
                context={"private": "excluded"},
            )
        )
    first = alice.get("/api/inbox?limit=20").json()
    second = alice.get("/api/inbox?offset=20&limit=20").json()
    assert first["total"] == second["total"] == 23
    assert len(first["items"]) == 20 and len(second["items"]) == 3
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
    assert alice.put("/api/inbox/read", json={"read": True}).status_code == 204
    assert alice.get("/api/inbox").json()["unread"] == 0
    assert bob.get("/api/inbox").json()["items"][0]["path"] == "/#/"
    assert bob.get("/api/inbox").json()["unread"] == 1
    assert admin.get("/api/inbox").json()["unread"] == 1
    assert alice.post("/api/inbox/opened").status_code == 204
