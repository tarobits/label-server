import io

from conftest import install, profile
from PIL import Image, ImageOps
from test_access import Policy

from app.access import Action
from app.models import PrintJob


def test_history_preview_matches_printed_pixels_and_survives_template_edits(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    document = {
        "print_resolution": "high",
        "elements": [
            {
                "id": "text",
                "kind": "text",
                "x": 2,
                "y": 2,
                "width": 40,
                "height": 12,
                "content": "Printed content",
            }
        ],
    }
    template = client.post("/api/templates", json={"name": "History", "document": document}).json()
    response = client.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["template_name"] == "History"
    assert job["template_snapshot"]["name"] == "History"
    client.app.state.fleet.workers["main"].tick()
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "printed"
    response = client.get(f"/api/jobs/{job['id']}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"].startswith("private")
    image = Image.open(io.BytesIO(response.content))
    assert image.size == (850, 170)
    printed = client.app.state.fleet.workers["main"].backend.batches[0][0]
    assert ImageOps.invert(image.convert("L")).convert("1").tobytes() == printed.raster
    document["elements"][0]["content"] = "Changed later"
    assert (
        client.put(
            f"/api/templates/{template['id']}",
            json={"name": "Changed", "document": document, "expected_revision": 1},
        ).status_code
        == 200
    )
    assert client.get(f"/api/jobs/{job['id']}/preview").content == response.content
    assert client.get("/api/queue/groups").json()[0]["jobs"][0]["template_name"] == "History"
    batches = client.get("/api/batches").json()
    detail = client.get(f"/api/batches/{batches[0]['id']}").json()
    item = detail["items"][0]
    assert (item["job_id"], item["length_mm"], item["width_mm"]) == (job["id"], 60, 24)
    assert client.get("/api/jobs/missing/preview").status_code == 404
    client.app.state.access_policy = Policy(Action.READ)
    assert client.get(f"/api/jobs/{job['id']}/preview").status_code == 403


def test_legacy_queue_names_use_the_saved_revision_without_rendering_previews(client, monkeypatch):
    tape = profile(client)
    template = client.post(
        "/api/templates", json={"name": "Original label name", "document": {}}
    ).json()
    queued = client.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": {}}
    ).json()
    with client.app.state.factory.begin() as session:
        job = session.get(PrintJob, queued["id"])
        snapshot = dict(job.template_snapshot)
        snapshot.pop("name")
        job.template_snapshot = snapshot
    assert (
        client.put(
            f"/api/templates/{template['id']}",
            json={"name": "Renamed label", "document": {}, "expected_revision": 1},
        ).status_code
        == 200
    )

    def no_render(*args, **kwargs):
        raise AssertionError("Queue listing must not render previews")

    monkeypatch.setattr("app.api.render_job", no_render)
    groups = client.get("/api/queue/groups?copy_state=queued")
    assert groups.status_code == 200
    assert groups.json()[0]["jobs"][0]["template_name"] == "Original label name"
