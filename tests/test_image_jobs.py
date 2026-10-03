import base64
import io
import json
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from conftest import install, profile
from fastapi.testclient import TestClient
from PIL import Image, ImageOps
from test_access import Policy

from app.access import Action
from app.main import create_app
from app.models import LabelCopy, PrintJob
from app.render import render_job
from scripts import submit_image


def upload(client, size=(200, 100)):
    output = io.BytesIO()
    Image.new("RGB", size, "black").save(output, format="PNG")
    response = client.post("/api/image-assets", content=output.getvalue())
    assert response.status_code == 201, response.text
    return response.json()["id"], output.getvalue()


def test_image_preview_matches_frozen_high_resolution_print_with_physical_band(client):
    tape = profile(client)
    install(client, tape["id"])
    asset, _ = upload(client)
    registry = client.app.state.registry
    device = registry.definition("main")
    registry._definitions["main"] = replace(
        device, capabilities=replace(device.capabilities, printable_widths_mm={"24": 18})
    )
    body = {
        "image_asset": asset,
        "tape_profile": tape["id"],
        "print_resolution": "high",
        "copies": 2,
    }
    response = client.post("/api/image-jobs/preview", json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    element = preview["resolved_elements"][0]
    assert (element["width"], element["height"], element["y"]) == (36, 18, 3)
    assert client.get("/api/jobs").json() == []
    response = client.post("/api/image-jobs", json=body)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "queued" and len(job["labels"]) == 2
    assert len(client.get("/api/templates").json()) == 1
    client.delete(f"/api/image-assets/{asset}")
    registry._definitions["main"] = device
    with client.app.state.factory() as session:
        frozen = render_job(
            session.get(PrintJob, job["id"]),
            session.get(LabelCopy, job["labels"][0]["id"]),
            images=client.app.state.images,
        )
    expected = Image.open(io.BytesIO(base64.b64decode(preview["png"].split(",")[1])))
    assert frozen.raster == ImageOps.invert(expected.convert("L")).convert("1").tobytes()
    assert (frozen.dpi_x, frozen.dpi_y) == (360, 180)
    client.put("/api/printer/automatic-printing", json={"held": True})
    client.app.state.worker.tick()
    assert client.app.state.worker.backend.batches == []
    assert client.post("/api/queue/print").status_code == 202
    client.app.state.worker.tick()
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "printed"


def test_fixed_length_fits_without_distorting_and_overlong_images_need_explicit_length(client):
    tape = profile(client)
    asset, _ = upload(client, (2000, 20))
    body = {"image_asset": asset, "tape_profile": tape["id"]}
    assert client.post("/api/image-jobs", json=body).status_code == 422
    response = client.post("/api/image-jobs/preview", json={**body, "length_mm": 40})
    assert response.status_code == 200, response.text
    result = response.json()
    element = result["resolved_elements"][0]
    assert result["length_mm"] == 40
    assert element["width"] / element["height"] == pytest.approx(100)
    assert element["y"] == pytest.approx((24 - element["height"]) / 2)
    assert client.get("/api/jobs").json() == []


def test_image_retries_are_atomic_survive_restart_and_share_key_namespace(client):
    tape = profile(client)
    asset, _ = upload(client)
    body = {"image_asset": asset, "tape_profile": tape["id"]}
    headers = {"Idempotency-Key": "image:event-1"}

    def submit(_):
        response = client.post("/api/image-jobs", json=body, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = list(executor.map(submit, range(4)))
    assert len({j["id"] for j in jobs}) == 1
    assert (
        client.post("/api/image-jobs", json={**body, "copies": 2}, headers=headers).status_code
        == 409
    )
    assert (
        client.post(
            "/api/jobs",
            json={"tape_profile": tape["id"], "data": {"text": "Different"}},
            headers=headers,
        ).status_code
        == 409
    )
    settings = client.app.state.settings
    client.__exit__(None, None, None)
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        assert restarted.post("/api/image-jobs", json=body, headers=headers).json() == jobs[0]
        assert len(restarted.get("/api/jobs").json()) == 1


def test_image_submission_obeys_policy_and_rejects_missing_assets(client):
    tape = profile(client)
    body = {"image_asset": "a" * 64, "tape_profile": tape["id"]}
    assert client.post("/api/image-jobs", json=body).status_code == 422
    asset, _ = upload(client)
    body["image_asset"] = asset
    client.app.state.access_policy = Policy(Action.SUBMIT)
    assert client.post("/api/image-jobs", json=body).status_code == 403
    assert client.post("/api/image-jobs/preview", json=body).status_code == 200
    client.app.state.access_policy = Policy(Action.READ)
    assert client.post("/api/image-jobs", json=body).status_code == 403
    assert client.get("/api/jobs").status_code == 403
    client.app.state.access_policy = Policy()
    assert client.get("/api/jobs").json() == []


def test_bridge_retries_lost_response_without_duplicates_and_previews_without_queuing(
    client, tmp_path, monkeypatch, capsys
):
    tape = profile(client)
    _, data = upload(client)
    image = tmp_path / "label with spaces.png"
    image.write_bytes(data)
    attempts = []

    def urlopen(request, timeout):
        parsed = urllib.parse.urlsplit(request.full_url)
        response = client.post(
            parsed.path + "?" + parsed.query,
            content=request.data,
            headers=dict(request.header_items()),
        )
        assert response.is_success, response.text
        attempts.append(parsed.path)
        if parsed.path == "/api/image-jobs" and attempts.count(parsed.path) == 1:
            raise TimeoutError("Server committed; response was lost")
        return io.BytesIO(response.content)

    monkeypatch.setattr(submit_image.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(submit_image.time, "sleep", lambda _: None)
    args = [str(image), "--profile", tape["id"], "--homebox", "--resolution", "high"]
    preview = tmp_path / "preview.html"
    submit_image.main([*args, "--preview", str(preview)])
    assert "image-rendering:pixelated" in preview.read_text()
    assert client.get("/api/jobs").json() == []
    capsys.readouterr()
    submit_image.main(args)
    first = json.loads(capsys.readouterr().out)
    submit_image.main(args)
    assert json.loads(capsys.readouterr().out)["id"] == first["id"]
    assert len(client.get("/api/jobs").json()) == 1
    assert len(client.get("/api/image-assets").json()) == 1
    # A new HomeBox invocation has a fresh filename, even with identical artwork.
    other = tmp_path / "label-another-event.png"
    other.write_bytes(data)
    submit_image.main([str(other), *args[1:]])
    assert len(client.get("/api/jobs").json()) == 2


def test_bridge_does_not_retry_conflicts(monkeypatch):
    calls = []

    def conflict(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(
            request.full_url, 409, "Conflict", {}, io.BytesIO(b"changed input")
        )

    monkeypatch.setattr(submit_image.urllib.request, "urlopen", conflict)
    with pytest.raises(SystemExit, match="changed input"):
        submit_image.request("http://testserver", "/image-jobs", {}, key="event")
    assert len(calls) == 1
