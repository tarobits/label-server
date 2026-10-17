import pytest
from conftest import install, job, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_fleet import device, fit, group, submit
from test_scoped_operations import grant

from app.models import FlushRequest, LabelCopy, PrinterState, PrintRun, State
from app.printer.base import LabelGeometry, RenderedLabel
from app.printer.brother import BrotherPTP710BT

accounts = account_fixture


def correct(client, cartridge, remaining):
    response = client.put(
        f"/api/cartridges/{cartridge['id']}/remaining", json={"remaining_mm": remaining}
    )
    assert response.status_code == 200, response.text


def assert_unreserved(client, count):
    with client.app.state.factory() as session:
        assert not list(session.scalars(select(FlushRequest)))
        copies = list(session.scalars(select(LabelCopy)))
        assert len(copies) == count
        assert all(copy.state == State.QUEUED for copy in copies)
        assert all(
            not state.automatic_printing_held for state in session.scalars(select(PrinterState))
        )


@pytest.mark.parametrize("path", ["/api/queue/print", "/api/destinations/main/print"])
def test_thousand_copies_warn_before_reservation_without_rasterizing(client, monkeypatch, path):
    tape = profile(client, threshold=10000)
    cartridge = install(client, tape["id"])
    assert (
        client.put("/api/printer/mock", json={"connected": True, "tape_width_mm": 24}).status_code
        == 200
    )
    queued = job(client, tape["id"], copies=1000)

    def no_render(*args, **kwargs):
        pytest.fail("Preflight must not rasterize a thousand saved labels")

    monkeypatch.setattr("app.render.render_document", no_render)
    response = client.post(path)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "tape_shortage"
    shortage = detail["shortages"][0]
    assert shortage["copies"] == 1000
    assert shortage["estimated_mm"] == queued["length_mm"] * 1000 + 20
    assert shortage["remaining_mm"] == 8000
    assert_unreserved(client, 1000)
    assert client.get("/api/cartridges").json()[0]["remaining_mm"] == cartridge["remaining_mm"]
    response = client.post(path, headers={"X-Tape-Shortage-Confirmation": detail["confirmation"]})
    assert response.status_code == 202, response.text
    with client.app.state.factory() as session:
        reserved = session.scalar(select(FlushRequest))
        assert set(reserved.copy_ids) == {label["id"] for label in queued["labels"]}
        assert all(copy.state == State.QUEUED for copy in session.scalars(select(LabelCopy)))


def test_selected_copies_only_and_stale_confirmation(client):
    tape = profile(client, threshold=10000)
    cartridge = install(client, tape["id"], remaining=100)
    queued = job(client, tape["id"], copies=1000)
    ids = [label["id"] for label in queued["labels"]]
    selected = {"copy_ids": ids[:3]}
    response = client.post("/api/queue/print", json=selected)
    detail = response.json()["detail"]
    assert detail["shortages"][0]["copies"] == 3
    assert detail["shortages"][0]["estimated_mm"] == 200
    assert_unreserved(client, 1000)
    correct(client, cartridge, 90)
    old_header = {"X-Tape-Shortage-Confirmation": detail["confirmation"]}
    stale = client.post("/api/queue/print", json=selected, headers=old_header)
    assert stale.status_code == 409
    fresh = stale.json()["detail"]
    assert fresh["confirmation"] != detail["confirmation"]
    assert fresh["shortages"][0]["remaining_mm"] == 90
    changed = client.post("/api/queue/print", json={"copy_ids": ids[3:6]}, headers=old_header)
    assert changed.status_code == 409
    assert changed.json()["detail"]["confirmation"] != detail["confirmation"]
    assert_unreserved(client, 1000)
    # One copy fits: unselected labels cannot inflate its estimate or require consent.
    response = client.post("/api/queue/print", json={"copy_ids": ids[:1]})
    assert response.status_code == 202, response.text
    with client.app.state.factory() as session:
        assert session.scalar(select(FlushRequest)).copy_ids == ids[:1]


def test_group_warns_all_printers_before_reserving_any(client):
    tapes = [profile(client, name=name, threshold=10000) for name in ("White", "Yellow")]
    second = device(client)
    dest = group(client, ["main", second])
    cartridges = [fit(client, printer, tape) for printer, tape in zip(("main", second), tapes)]
    for cartridge in cartridges:
        correct(client, cartridge, 100)
    jobs = [submit(client, dest, tape, copies=3) for tape in tapes]
    selected = {"copy_ids": [label["id"] for queued in jobs for label in queued["labels"]]}
    response = client.post(f"/api/destinations/{dest}/print", json=selected)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert {item["printer_id"] for item in detail["shortages"]} == {"main", second}
    assert all(item["copies"] == 3 for item in detail["shortages"])
    assert_unreserved(client, 6)
    assert not next(item for item in client.get("/api/destinations").json() if item["id"] == dest)[
        "automatic_printing_held"
    ]
    response = client.post(
        f"/api/destinations/{dest}/print",
        json=selected,
        headers={"X-Tape-Shortage-Confirmation": detail["confirmation"]},
    )
    assert response.status_code == 202, response.text
    assert len(response.json()["requests"]) == 2


def test_csv_printer_assignment_rolls_back_when_warning_is_declined(client):
    tape = profile(client, threshold=10000)
    second = device(client)
    dest = group(client, ["main", second])
    for printer in ("main", second):
        correct(client, fit(client, printer, tape), 10)
    response = client.post(
        "/api/runs/prepare",
        json={
            "destination_id": dest,
            "request_key": "shortage-run",
            "name": "Run",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nOne\nTwo",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2}, {"source_row": 3}],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert client.post(f"/api/runs/{run['id']}/submit").status_code == 200
    response = client.post(f"/api/destinations/{dest}/print")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "tape_shortage"
    assert_unreserved(client, 2)
    with client.app.state.factory() as session:
        assert session.get(PrintRun, run["id"]).assigned_printer_id is None


def test_preflight_uses_saved_geometry_and_backend_estimate(client):
    tape = profile(client, threshold=10000)
    install(client, tape["id"], remaining=1)
    queued = job(client, tape["id"], copies=2)
    backend = client.app.state.registry.backend("main")
    received = []

    def estimate(labels):
        received.extend(labels)
        return 987.5

    backend.estimate_consumption = estimate
    response = client.post("/api/queue/print")
    assert response.status_code == 409
    assert response.json()["detail"]["shortages"][0]["estimated_mm"] == 987.5
    assert all(isinstance(label, LabelGeometry) for label in received)
    assert {label.copy_id for label in received} == {label["id"] for label in queued["labels"]}
    assert all(label.length_mm == queued["length_mm"] for label in received)


@pytest.mark.parametrize("dpi_x", [180, 360])
@pytest.mark.parametrize("cut_each", [False, True])
def test_brother_preflight_matches_print_estimate_including_feed_and_minimum_length(
    dpi_x, cut_each
):
    # No transport access: both estimates must agree for saved dimensions at either resolution.
    backend = BrotherPTP710BT(object(), feed_mm=3, leader_mm=25, cut_each=cut_each)
    lengths = [8, 14, 60]
    geometry = [LabelGeometry(str(i), 24, length, dpi_x, 180) for i, length in enumerate(lengths)]
    rendered = [
        RenderedLabel(label.copy_id, 24, label.length_mm, 1, 1, b"\x00", dpi_x=dpi_x)
        for label in geometry
    ]
    assert backend.estimate_consumption(geometry) == backend.plan_batch(rendered).estimated_mm
    assert backend.estimate_consumption(geometry) > sum(lengths) + 25


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1])
def test_invalid_backend_estimate_cannot_reserve_queue(client, invalid):
    tape = profile(client, threshold=10000)
    install(client, tape["id"])
    job(client, tape["id"])
    client.app.state.registry.backend("main").estimate_consumption = lambda labels: invalid
    assert client.post("/api/queue/print").status_code == 422
    assert_unreserved(client, 1)


@pytest.mark.parametrize("level", ["print", "moderator"])
@pytest.mark.parametrize("remaining", [10, 8000])
def test_group_only_access_can_confirm_shortage_without_direct_printer_access(
    accounts, level, remaining
):
    admin, alice, _ = accounts
    dest = group(admin, ["main"])
    grant(admin, "alice", dest, level)
    tape = profile(admin, threshold=10000)
    fit(admin, "main", tape)
    worker = admin.app.state.fleet.workers["main"]
    worker.latest_status = worker.backend.get_status()
    cartridge = admin.get("/api/cartridges").json()[0]
    correct(admin, cartridge, remaining)
    queued = submit(alice, dest, tape, copies=2)
    ids = {"copy_ids": [label["id"] for label in queued["labels"]]}
    assert alice.get("/api/printers").json() == []
    response = alice.post(f"/api/destinations/{dest}/print", json=ids)
    if remaining == 10:
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "tape_shortage"
        assert_unreserved(admin, 2)
        # Even a valid group warning acknowledgment cannot grant direct printer access.
        header = {"X-Tape-Shortage-Confirmation": detail["confirmation"]}
        assert (
            alice.post("/api/destinations/main/print", json=ids, headers=header).status_code == 403
        )
        response = alice.post(f"/api/destinations/{dest}/print", json=ids, headers=header)
    assert response.status_code == 202, response.text
