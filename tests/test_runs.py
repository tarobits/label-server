from typing import Any

import pytest
from conftest import install, profile
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.models import PrintJob


def run_body(client: TestClient) -> dict[str, Any]:
    tape = profile(client, threshold=1)
    return {
        "request_key": "example",
        "name": "Assets",
        "template": "text",
        "expected_revision": 2,
        "tape_profile": tape["id"],
        "csv_text": 'Title,Note\n"First, label",a\nSecond,b\n',
        "mapping": {"text": "Title"},
        "rows": [{"source_row": 3, "copies": 2}, {"source_row": 2, "copies": 1}],
    }


def test_run_freezes_preview_and_submits_once_in_order(client: TestClient) -> None:
    body = run_body(client)
    install(client, body["tape_profile"])
    response = client.post("/api/runs/prepare", json=body)
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["copies"] == 3 and run["estimated_mm"] == 200
    assert client.get("/api/jobs").json() == []
    client.app.state.worker.tick()
    assert not client.app.state.worker.backend.batches
    preview = client.get(f"/api/runs/{run['id']}/rows/0/preview").json()
    template = client.get("/api/templates/text").json()
    template["document"]["elements"][0]["content"] = "Changed"
    client.put(
        "/api/templates/text",
        json={"name": "Changed", "document": template["document"], "expected_revision": 2},
    )
    client.delete("/api/templates/text")
    assert client.get(f"/api/runs/{run['id']}/rows/0/preview").json() == preview
    assert client.post("/api/runs/prepare", json=body).json()["run"]["id"] == run["id"]
    client.put("/api/printer/automatic-printing", json={"held": True})
    submitted = client.post(f"/api/runs/{run['id']}/submit").json()
    assert [j["source_row"] for j in submitted["jobs"]] == [3, 2]
    assert [j["payload"]["text"] for j in submitted["jobs"]] == ["Second", "First, label"]
    retry = client.post(f"/api/runs/{run['id']}/submit").json()
    assert [j["id"] for j in retry["jobs"]] == [j["id"] for j in submitted["jobs"]]
    client.app.state.worker.tick()
    assert not client.app.state.worker.backend.batches
    client.post("/api/queue/print")
    client.app.state.worker.tick()
    expected = [copy["id"] for job in submitted["jobs"] for copy in job["labels"]]
    assert [label.copy_id for label in client.app.state.worker.backend.batches[0]] == expected


def test_invalid_rows_never_create_partial_run(client: TestClient) -> None:
    body = run_body(client)
    body["csv_text"] = "Title,Note\n,a\nValid,b\n"
    result = client.post("/api/runs/prepare", json=body).json()
    assert not result["valid"]
    assert result["errors"][0]["source_row"] == 2
    assert client.get("/api/runs").json() == []
    assert client.get("/api/jobs").json() == []


@pytest.mark.parametrize(
    "csv_text",
    ["a,a\n1,2", "a,b\n1", 'a\n"unterminated', "a\n" + ("x" * 2001), "a\n" + ("x\n" * 251)],
)
def test_csv_rejects_bad_structure_and_limits(client: TestClient, csv_text: str) -> None:
    assert client.post("/api/csv/parse", json={"csv_text": csv_text}).status_code == 422


def test_csv_multiline_bom_semicolon_and_literal_formula(client: TestClient) -> None:
    result = client.post(
        "/api/csv/parse",
        json={"csv_text": '\ufeffTitle;Note\r\n"line 1\nline 2";=1+1\r\n', "delimiter": ";"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["rows"] == [{"source_row": 2, "values": ["line 1\nline 2", "=1+1"]}]


def test_submission_rolls_back_all_rows_and_is_retryable(client: TestClient) -> None:
    run = client.post("/api/runs/prepare", json=run_body(client)).json()["run"]

    def fail_second(mapper: Any, connection: Any, target: PrintJob) -> None:
        if target.run_position == 1:
            raise RuntimeError("Injected insert failure")

    event.listen(PrintJob, "before_insert", fail_second)
    try:
        with pytest.raises(RuntimeError, match="Injected"):
            client.post(f"/api/runs/{run['id']}/submit")
    finally:
        event.remove(PrintJob, "before_insert", fail_second)
    assert client.get("/api/jobs").json() == []
    assert client.get(f"/api/runs/{run['id']}").json()["submitted_at"] is None
    assert len(client.post(f"/api/runs/{run['id']}/submit").json()["jobs"]) == 2


def test_request_key_conflict_and_selection_validation(client: TestClient) -> None:
    body = run_body(client)
    assert client.post("/api/runs/prepare", json=body).json()["valid"]
    body["name"] = "Different"
    assert client.post("/api/runs/prepare", json=body).status_code == 409
    body["request_key"] = "other"
    body["rows"] = [{"source_row": 2}, {"source_row": 2}]
    assert client.post("/api/runs/prepare", json=body).status_code == 422
    body["rows"] = [{"source_row": 2, "copies": 1000}, {"source_row": 3}]
    assert client.post("/api/runs/prepare", json=body).status_code == 422


def test_draft_and_submitted_run_survive_restart(client: TestClient) -> None:
    from app.main import create_app

    run = client.post("/api/runs/prepare", json=run_body(client)).json()["run"]
    settings = client.app.state.settings
    client.__exit__(None, None, None)
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        assert restarted.get(f"/api/runs/{run['id']}").json()["submitted_at"] is None
        assert restarted.get(f"/api/runs/{run['id']}/rows/0/preview").status_code == 200
        jobs = restarted.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        assert [
            j["id"] for j in restarted.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
        ] == [j["id"] for j in jobs]


def test_run_interruption_preserves_copy_review_and_retry_order(client: TestClient) -> None:
    body = run_body(client)
    install(client, body["tape_profile"])
    run = client.post("/api/runs/prepare", json=body).json()["run"]
    jobs = client.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
    ids = [copy["id"] for job in jobs for copy in job["labels"]]
    worker = client.app.state.worker
    worker.backend.fail_after = 1
    worker.tick()
    assert client.get(f"/api/jobs/{jobs[0]['id']}").json()["labels"][0]["state"] == "printed"
    batch = client.get("/api/batches").json()[0]
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review",
            json={"decisions": {i: "queued" for i in ids[1:]}, "consumed_mm": 60},
        ).status_code
        == 200
    )
    worker.tick()
    assert [label.copy_id for label in worker.backend.batches[1]] == ids[1:]


def test_run_migration_keeps_existing_jobs_and_copies(client: TestClient) -> None:
    from alembic import command
    from alembic.config import Config
    from conftest import job

    from app.main import create_app

    tape = profile(client)
    original = job(client, tape["id"], 2)
    settings = client.app.state.settings
    client.__exit__(None, None, None)
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    command.downgrade(config, "9c421df5a901")
    command.upgrade(config, "head")
    command.check(config)
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        restored = restarted.get(f"/api/jobs/{original['id']}").json()
        assert restored["labels"] == original["labels"]
        assert restored["template_snapshot"] == original["template_snapshot"]
        assert restored["run_id"] is None


def test_draft_deletion_cannot_delete_submitted_runs(client: TestClient) -> None:
    body = run_body(client)
    draft = client.post("/api/runs/prepare", json=body).json()["run"]
    assert client.delete(f"/api/runs/{draft['id']}").status_code == 200
    assert client.get(f"/api/runs/{draft['id']}").status_code == 404
    assert client.post(f"/api/runs/{draft['id']}/submit").status_code == 404
    assert client.get("/api/jobs").json() == []
    run = client.post("/api/runs/prepare", json=body).json()["run"]
    assert client.post(f"/api/runs/{run['id']}/submit").status_code == 200
    assert client.delete(f"/api/runs/{run['id']}").status_code == 409
    assert len(client.get("/api/jobs").json()) == 2


def test_group_pagination_keeps_full_run_and_applies_filters(client: TestClient) -> None:
    from conftest import job

    body = run_body(client)
    body["csv_text"] = "Title\n" + "\n".join(f"Row {i}" for i in range(30))
    body["rows"] = [{"source_row": i + 2} for i in range(30)]
    single = job(client, body["tape_profile"])
    run = client.post("/api/runs/prepare", json=body).json()["run"]
    submitted = client.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
    groups = client.get(
        "/api/queue/groups",
        params={"limit": 1, "copy_state": "queued", "profile_id": body["tape_profile"]},
    ).json()
    assert len(groups) == 1 and groups[0]["run_id"] == run["id"]
    assert [job["source_row"] for job in groups[0]["jobs"]] == list(range(2, 32))
    assert (
        client.get("/api/queue/groups", params={"limit": 1, "offset": 1}).json()[0]["jobs"][0]["id"]
        == single["id"]
    )
    client.delete(f"/api/jobs/{submitted[0]['id']}")
    filtered = client.get("/api/queue/groups", params={"copy_state": "cancelled"}).json()
    assert len(filtered) == 1 and len(filtered[0]["jobs"]) == 1
    assert client.get("/api/queue/groups", params={"profile_id": "absent"}).json() == []
