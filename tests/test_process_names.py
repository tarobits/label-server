from conftest import install, profile
from test_access_security import accounts as accounts
from test_runs import run_body

from app.submissions import input_fingerprint


def test_process_name_and_populated_fields_survive_into_queue_and_history(client):
    tape = profile(client, name="Original tape", threshold=1)
    install(client, tape["id"])
    document = {
        "fields": [
            {"name": "text", "label": "Cable number", "sample": "CABLE-42"},
            {"name": "location", "label": "Location", "default": "Office"},
        ],
        "elements": [
            {
                "id": "text",
                "kind": "text",
                "content": "{{text}}",
                "x": 2,
                "y": 4,
                "width": 40,
                "height": 12,
            }
        ],
    }
    created = client.post("/api/templates", json={"name": "Cable labels", "document": document})
    assert created.status_code == 201, created.text
    template = created.json()
    response = client.post(
        "/api/jobs",
        json={
            "process_name": "Network upgrade",
            "template": template["id"],
            "tape_profile": tape["id"],
            "data": {"text": "CABLE-42"},
        },
    )
    assert response.status_code == 201, response.text
    queued = response.json()
    assert queued["process_name"] == "Network upgrade"
    assert queued["template_name"] == "Cable labels"
    assert queued["profile_name"] == "Original tape"
    assert queued["printer_name"] == "Mock printer"
    assert queued["payload"] == {"text": "CABLE-42"}
    assert queued["fields"] == [
        {"name": "text", "label": "Cable number", "value": "CABLE-42"},
        {"name": "location", "label": "Location", "value": "Office"},
    ]
    assert (
        client.put(
            f"/api/templates/{template['id']}",
            json={
                "name": "Changed template",
                "document": document,
                "expected_revision": 1,
            },
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/tape-profiles/{tape['id']}",
            json={
                "name": "Renamed tape",
                "width_mm": 24,
                "auto_print_threshold": 1,
            },
        ).status_code
        == 200
    )
    group = client.get("/api/queue/groups?copy_state=queued").json()[0]
    assert group["jobs"][0]["process_name"] == "Network upgrade"
    client.app.state.fleet.workers["main"].tick()
    batch = client.get("/api/batches").json()[0]
    assert batch["process_names"] == ["Network upgrade"]
    item = client.get(f"/api/batches/{batch['id']}").json()["items"][0]
    for field in (
        "process_name",
        "template_name",
        "template_revision",
        "profile_name",
        "printer_name",
        "fields",
    ):
        assert item[field] == queued[field]


def test_default_process_name_uses_the_template_not_label_text(client):
    tape = profile(client)
    result = client.post(
        "/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Not a process name"}}
    ).json()
    assert result["process_name"] == "Simple text"
    assert result["fields"][0]["value"] == "Not a process name"


def test_csv_process_name_is_frozen_with_every_row(client):
    body = {**run_body(client), "process_name": "Inventory stocktake"}
    prepared = client.post("/api/runs/prepare", json=body).json()["run"]
    assert prepared["process_name"] == "Inventory stocktake"
    jobs = client.post(f"/api/runs/{prepared['id']}/submit").json()["jobs"]
    assert [job["process_name"] for job in jobs] == ["Inventory stocktake"] * 2
    assert [job["fields"][0]["value"] for job in jobs] == ["Second", "First, label"]


def test_request_approval_preserves_process_name_fields_and_people(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    response = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "process_name": "Cable installation",
                "tape_profile": tape["id"],
                "data": {"text": "Rack 7"},
            },
        },
    )
    assert response.status_code == 201, response.text
    requested = response.json()
    assert requested["labels"][0]["template_snapshot"]["process_name"] == "Cable installation"
    approval = admin.post(f"/api/requests/{requested['id']}/approve").json()
    job = admin.get(f"/api/jobs/{approval['job_ids'][0]}").json()
    assert job["process_name"] == "Cable installation"
    assert job["fields"][0]["value"] == "Rack 7"
    assert job["attribution"]["requested_by"]["name"] == "alice"
    assert job["attribution"]["authorization"]["actor"]["name"] == "administrator"


def test_process_name_validation_and_retry_keys(client):
    tape = profile(client)
    body = {"tape_profile": tape["id"], "data": {"text": "Retry"}, "process_name": "Process A"}
    headers = {"Idempotency-Key": "process-name-retry"}
    first = client.post("/api/jobs", json=body, headers=headers)
    assert first.status_code == 201
    assert client.post("/api/jobs", json=body, headers=headers).json()["id"] == first.json()["id"]
    assert (
        client.post(
            "/api/jobs", json={**body, "process_name": "Process B"}, headers=headers
        ).status_code
        == 409
    )
    for name in ("", "   ", "x" * 101):
        assert client.post("/api/jobs", json={**body, "process_name": name}).status_code == 422
    assert input_fingerprint({"data": {}}) == input_fingerprint({"data": {}, "process_name": None})
    assert input_fingerprint({"kind": "job", "input": {"data": {}}}) == input_fingerprint(
        {"kind": "job", "input": {"data": {}, "process_name": None}}
    )
