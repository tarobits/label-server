"""Manual printing explains destination failures without partially reserving work."""

import pytest
from conftest import profile
from sqlalchemy import select
from test_fleet import device, fit, group, submit

from app.models import Batch, FlushRequest, LabelCopy, PrintJob, PrintRun, State
from app.printer.base import PrinterStatus


def print_selected(client, destination, *jobs):
    return client.post(
        f"/api/destinations/{destination}/print",
        json={"copy_ids": [copy["id"] for job in jobs for copy in job["labels"]]},
    )


def assert_unreserved(client):
    with client.app.state.factory() as session:
        assert session.scalar(select(FlushRequest)) is None
        assert all(copy.state == State.QUEUED for copy in session.scalars(select(LabelCopy)))


@pytest.mark.parametrize("installed", [False, True])
def test_missing_exact_cartridge_names_required_profile_and_destination(client, installed):
    tape = profile(client, name="White")
    if installed:
        fit(client, "main", profile(client, name="Yellow"))
    # A matching cartridge elsewhere must not count as a selected destination.
    other = device(client, "Elsewhere")
    fit(client, other, tape)
    job = submit(client, "main", tape)
    response = print_selected(client, "main", job)
    assert response.status_code == 409
    message = response.json()["detail"]
    assert "No printer in the selected destination" in message
    assert '"White" (24 mm)' in message
    assert "Mock printer" in message
    assert "Elsewhere" not in message
    assert "offline" not in message
    assert_unreserved(client)


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("offline", "is offline"),
        ("printing", "is currently printing"),
        ("error", "reports an error: Cover open"),
        ("review", "has a batch awaiting review"),
        ("width", "detects 12 mm tape, but these labels require 24 mm tape"),
        ("no_width", "detects no tape width"),
    ],
)
def test_matching_cartridge_explains_specific_blocker(client, condition, expected, selected):
    tape = profile(client)
    cartridge = fit(client, "main", tape)
    job = submit(client, "main", tape)
    worker = client.app.state.fleet.workers["main"]
    if condition in ("printing", "review"):
        with client.app.state.factory.begin() as session:
            session.add(
                Batch(
                    printer_id="main",
                    cartridge_id=cartridge["id"],
                    state=State.PRINTING if condition == "printing" else State.NEEDS_REVIEW,
                    estimated_mm=30,
                )
            )
    else:
        worker.latest_status = PrinterStatus(
            condition != "offline",
            None if condition == "no_width" else 12 if condition == "width" else 24,
            "Cover open" if condition == "error" else None,
        )
    response = (
        print_selected(client, "main", job)
        if selected
        else client.post("/api/destinations/main/print")
    )
    assert response.status_code == 409
    message = response.json()["detail"]
    assert expected in message
    assert '"Mock printer"' in message
    assert '"White" (24 mm)' in message
    assert "Selection changed" not in message
    assert_unreserved(client)


def test_group_lists_each_matching_printer_blocker_and_uses_ready_member(client):
    tape = profile(client)
    second = device(client, "Packing")
    destination = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    job = submit(client, destination, tape)
    workers = client.app.state.fleet.workers
    workers["main"].latest_status = PrinterStatus(False, None)
    workers[second].latest_status = PrinterStatus(True, 24, "Cover open")
    response = print_selected(client, destination, job)
    assert response.status_code == 409
    message = response.json()["detail"]
    assert '"Mock printer" is offline' in message
    assert '"Packing" reports an error: Cover open' in message
    assert_unreserved(client)
    workers[second].latest_status = PrinterStatus(True, 24)
    response = print_selected(client, destination, job)
    assert response.status_code == 202, response.text
    assert response.json()["requests"][0]["printer_id"] == second


def test_mixed_selection_reports_all_failures_and_reserves_nothing(client):
    white = profile(client)
    yellow = profile(client, name="Yellow")
    blue = profile(client, name="Blue")
    second = device(client, "Packing")
    destination = group(client, ["main", second])
    fit(client, "main", white)
    fit(client, second, yellow)
    jobs = [submit(client, destination, tape, copies=2) for tape in (white, yellow, blue)]
    client.app.state.fleet.workers[second].latest_status = PrinterStatus(False, None)
    response = print_selected(client, destination, *jobs)
    assert response.status_code == 409
    message = response.json()["detail"]
    assert message.count('"Packing" is offline') == 1
    assert '"Blue" (24 mm)' in message
    assert '"White"' not in message
    assert_unreserved(client)


def test_actual_stale_selection_is_separate_from_printer_failure(client):
    tape = profile(client)
    job = submit(client, "main", tape)
    with client.app.state.factory.begin() as session:
        session.get(LabelCopy, job["labels"][0]["id"]).state = State.CANCELLED
    response = print_selected(client, "main", job)
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Some selected copies are no longer queued or available to you. Refresh the queue"
    )


def test_assigned_run_cannot_silently_fail_over_and_explains_assignment(client):
    tape = profile(client)
    second = device(client, "Packing")
    destination = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    prepared = client.post(
        "/api/runs/prepare",
        json={
            "destination_id": destination,
            "request_key": "blocked-run",
            "name": "Run",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nOne",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    run = prepared.json()["run"]
    jobs = client.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
    with client.app.state.factory.begin() as session:
        session.get(PrintRun, run["id"]).assigned_printer_id = "main"
    client.app.state.fleet.workers["main"].latest_status = PrinterStatus(False, None)
    response = print_selected(client, destination, *jobs)
    assert response.status_code == 409
    assert 'This run is assigned to "Mock printer"' in response.json()["detail"]
    assert '"Mock printer" is offline' in response.json()["detail"]
    assert "Packing" not in response.json()["detail"]
    assert_unreserved(client)


def test_saved_geometry_mismatch_is_not_reported_as_offline(client):
    tape = profile(client)
    fit(client, "main", tape)
    job = submit(client, "main", tape)
    with client.app.state.factory.begin() as session:
        saved = session.get(PrintJob, job["id"])
        saved.template_snapshot = {
            **saved.template_snapshot,
            "render_spec": {**saved.template_snapshot["render_spec"], "dpi": 999},
        }
    response = print_selected(client, "main", job)
    assert response.status_code == 409
    assert "saved resolution or printable area" in response.json()["detail"]
    assert_unreserved(client)
