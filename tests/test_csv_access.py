"""Preparing a private CSV draft needs Request access, never configuration access."""

import pytest
from conftest import profile
from test_access_security import accounts as account_fixture

from app.models import Role

accounts = account_fixture


@pytest.mark.parametrize("level", ["request", "print"])
@pytest.mark.parametrize("group_destination", [False, True])
def test_csv_preparation_and_submission_follow_destination_level(
    accounts, level, group_destination
):
    admin, alice, _ = accounts
    destination = "main"
    if group_destination:
        created = admin.post(
            "/api/printer-groups", json={"name": "Distribution", "printer_ids": ["main"]}
        )
        assert created.status_code == 201, created.text
        destination = created.json()["id"]
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": destination, "level": level}
        ]
    tape = profile(admin)
    prepared = alice.post(
        "/api/runs/prepare",
        json={
            "request_key": "csv-access-test",
            "name": "Private draft",
            "destination_id": destination,
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nFrozen CSV label\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["valid"]
    run = prepared.json()["run"]
    assert run["owner_id"] == "alice"
    assert run["destination_id"] == destination
    assert run["submitted_at"] is None
    assert alice.get("/api/jobs").json() == []
    submitted = alice.post(f"/api/runs/{run['id']}/submit")
    if level == "print":
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["jobs"][0]["authorization_basis"] == "print"
        assert alice.get("/api/requests").json() == []
    else:
        assert submitted.status_code == 403, submitted.text
        requested = alice.post("/api/requests", json={"kind": "run", "run_id": run["id"]})
        assert requested.status_code == 201, requested.text
        assert requested.json()["status"] == "pending"
        assert alice.get("/api/jobs").json() == []
        approved = admin.post(f"/api/requests/{requested.json()['id']}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
    queued = alice.get("/api/jobs").json()
    assert len(queued) == 1
    assert queued[0]["owner_id"] == "alice"
    assert queued[0]["destination_id"] == destination
    assert queued[0]["authorization_basis"] == level
