"""Sidebar counts share request visibility and are independent of list pagination."""

from test_access_security import accounts as account_fixture

from app.models import Role
from app.printing.request_models import PrintRequest

accounts = account_fixture


def test_pending_request_counts_respect_ownership_moderation_and_status(accounts):
    admin, alice, bob = accounts
    with admin.app.state.factory.begin() as session:
        for owner, destination, status, quantity in [
            ("alice", "main", "pending", 205),
            ("bob", "main", "pending", 1),
            ("bob", "other", "pending", 1),
            ("alice", "main", "approved", 1),
            ("alice", "main", "rejected", 1),
        ]:
            for _ in range(quantity):
                session.add(
                    PrintRequest(
                        owner_id=owner,
                        destination_id=destination,
                        status=status,
                        kind="job",
                        request_hash="test-only",
                        labels=[],
                    )
                )

    def count(client):
        response = client.get("/api/workspace")
        assert response.status_code == 200
        return response.json()["pending_requests"]

    assert count(admin) == 207
    assert count(alice) == 205
    assert count(bob) == 2
    assert len(alice.get("/api/requests").json()) == 200
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "moderator"}
        ]
    assert count(alice) == 206  # Own requests are not counted twice.
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = []
    assert count(alice) == 205
