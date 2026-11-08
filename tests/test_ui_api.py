from pathlib import Path

from app_client import TestClient
from conftest import create_test_app as create_app
from conftest import install, job, profile


def test_mock_controls_interrupt_once_and_link_to_review(client: TestClient) -> None:
    tape = profile(client, threshold=2)
    install(client, tape["id"])
    assert (
        client.put(
            "/api/printer/mock",
            json={
                "connected": True,
                "tape_width_mm": 24,
                "fail_after": 1,
            },
        ).status_code
        == 200
    )
    queued = job(client, tape["id"], 2)
    client.app.state.fleet.workers["main"].tick()
    batch = client.get("/api/batches").json()[0]
    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert detail["items"][0]["text"] == "example"
    assert detail["items"][0]["copy_number"] == 1
    assert detail["items"][0]["job_id"] == queued["id"]
    assert client.get("/api/printer/mock").json()["fail_after"] is None
    assert client.get("/api/notifications").json()[0]["path"] == f"/#/batches/{batch['id']}"


def test_mock_controls_are_validated_and_locked_during_printing(client: TestClient) -> None:
    assert (
        client.put(
            "/api/printer/mock",
            json={
                "connected": True,
                "tape_width_mm": -1,
            },
        ).status_code
        == 422
    )
    worker = client.app.state.fleet.workers["main"]
    with worker.printer_lock:
        assert client.put("/api/printer/mock", json={"connected": False}).status_code == 409
    assert (
        client.put(
            "/api/printer/mock",
            json={
                "connected": False,
                "tape_width_mm": None,
            },
        ).status_code
        == 200
    )
    status = client.get("/api/status").json()
    assert status["connected"] is False
    assert status["detected_width_mm"] is None


def test_job_filters_and_pending_flush_status(client: TestClient) -> None:
    tape = profile(client)
    install(client, tape["id"])
    cancelled = job(client, tape["id"])
    queued = job(client, tape["id"])
    client.delete(f"/api/jobs/{cancelled['id']}")
    results = client.get("/api/jobs?copy_state=queued").json()
    assert [item["id"] for item in results] == [queued["id"]]
    assert client.get("/api/jobs?copy_state=invalid").status_code == 422
    flush = client.post("/api/queue/print").json()
    assert client.get("/api/status").json()["pending_flush"] == flush["id"]
    client.app.state.fleet.workers["main"].tick()
    assert client.get("/api/status").json()["pending_flush"] is None


def test_frontend_is_served_without_masking_unknown_api_routes(
    client: TestClient, tmp_path: Path
) -> None:
    (tmp_path / "index.html").write_text("<html><body>Label room</body></html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "main.js").write_text("console.log('test')")
    icons = {
        "favicon.ico": "image/vnd.microsoft.icon",
        "favicon.svg": "image/svg+xml",
        "apple-touch-icon.png": "image/png",
        "apple-touch-icon-precomposed.png": "image/png",
        "pwa-192x192.png": "image/png",
        "pwa-512x512.png": "image/png",
        "pwa-maskable-512x512.png": "image/png",
    }
    public = Path(__file__).resolve().parent.parent / "frontend" / "public"
    for name in icons:
        (tmp_path / name).write_bytes((public / name).read_bytes())
    (tmp_path / "private.txt").write_text("Must not be served")
    settings = client.app.state.settings.model_copy(update={"frontend_dist": tmp_path})
    # Static routes can be exercised without entering a second application lifespan.
    app = create_app(settings, start_worker=False)
    static_client = TestClient(app)
    assert static_client.get("/").headers["content-type"].startswith("text/html")
    assert static_client.get("/").headers["cache-control"] == "no-cache"
    assert static_client.get("/index.html").content == static_client.get("/").content
    assert static_client.get("/index.html").headers["cache-control"] == "no-cache"
    assert static_client.get("/assets/main.js").status_code == 200
    for name, media_type in icons.items():
        response = static_client.get(f"/{name}")
        assert response.status_code == 200
        # Python's MIME database can use either registered ICO type depending on the OS.
        assert response.headers["content-type"] in (
            {"image/x-icon", media_type} if name.endswith(".ico") else {media_type}
        )
        assert response.content == (public / name).read_bytes()
    assert static_client.get("/private.txt").status_code == 404
    (tmp_path / "favicon.ico").unlink()
    assert static_client.get("/favicon.ico").status_code == 404
    assert static_client.get("/api/not-a-route").status_code == 404
    assert static_client.get("/openapi.json").status_code == 200
    static_client.close()
    app.state.engine.dispose()


def test_pwa_assets_have_explicit_types_and_require_revalidation(
    client: TestClient, tmp_path: Path
) -> None:
    assets = {
        "manifest.webmanifest": ('{"name":"Label Room"}', "application/manifest+json"),
        "sw.js": ("self.addEventListener('install', () => {})", "text/javascript"),
    }
    for name, (content, _) in assets.items():
        (tmp_path / name).write_text(content)
    settings = client.app.state.settings.model_copy(update={"frontend_dist": tmp_path})
    app = create_app(settings, start_worker=False)
    static_client = TestClient(app)
    try:
        for name, (content, media_type) in assets.items():
            response = static_client.get(f"/{name}")
            assert response.status_code == 200
            assert response.text == content
            assert response.headers["content-type"].split(";")[0] == media_type
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["x-content-type-options"] == "nosniff"
            (tmp_path / name).unlink()
            assert static_client.get(f"/{name}").status_code == 404
    finally:
        static_client.close()
        app.state.engine.dispose()
