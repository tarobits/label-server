from concurrent.futures import ThreadPoolExecutor

from conftest import create_test_app as create_app
from conftest import profile
from fastapi.testclient import TestClient


def test_job_retry_returns_same_frozen_job_and_rejects_changed_input(client: TestClient) -> None:
    tape = profile(client)
    body = {"tape_profile": tape["id"], "data": {"text": "Retry"}, "copies": 2}
    headers = {"Idempotency-Key": "integration:event-1"}
    first = client.post("/api/jobs", json=body, headers=headers)
    assert first.status_code == 201, first.text
    client.delete("/api/templates/text")
    retry = client.post("/api/jobs", json=body, headers=headers)
    assert retry.json()["id"] == first.json()["id"]
    assert retry.json()["template_snapshot"] == first.json()["template_snapshot"]
    assert len(client.get("/api/jobs").json()) == 1
    assert client.post("/api/jobs", json={**body, "copies": 3}, headers=headers).status_code == 409
    settings = client.app.state.settings
    client.__exit__(None, None, None)
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        assert (
            restarted.post("/api/jobs", json=body, headers=headers).json()["id"]
            == first.json()["id"]
        )


def test_concurrent_retries_commit_one_job(client: TestClient) -> None:
    tape = profile(client)
    body = {"tape_profile": tape["id"], "data": {"text": "Concurrent"}}

    def submit(_: int) -> str:
        response = client.post("/api/jobs", json=body, headers={"Idempotency-Key": "concurrent"})
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert len(set(executor.map(submit, range(4)))) == 1
    assert len(client.get("/api/jobs").json()) == 1


def test_bad_key_does_not_create_a_job(client: TestClient) -> None:
    tape = profile(client)
    assert (
        client.post(
            "/api/jobs",
            json={"tape_profile": tape["id"], "data": {"text": "Bad"}},
            headers={"Idempotency-Key": "not valid"},
        ).status_code
        == 422
    )
    assert client.get("/api/jobs").json() == []
