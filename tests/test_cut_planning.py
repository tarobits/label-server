"""Short-label warnings and immutable physical-output estimates, without hardware I/O."""

import copy
from dataclasses import replace

import pytest
from alembic import command
from alembic.config import Config
from conftest import install, profile
from printer_factory import BrowserPrinter
from sqlalchemy import create_engine, inspect

from app.models import Batch
from app.printer.base import LabelGeometry, PrintInterrupted, PrintResult
from app.printer.brother import BrotherPTP710BT
from app.printer.factory import configured_printer


@pytest.mark.parametrize("dpi_x", [180, 360])
def test_short_cut_plan_accounts_for_feed_and_padding_on_12mm_tape(dpi_x):
    backend = BrotherPTP710BT(object())
    labels = [LabelGeometry(str(i), 12, length, dpi_x) for i, length in enumerate((10, 18, 60))]
    plan = backend.plan_batch(labels)
    assert plan.minimum_cut_length_mm == 24.5
    assert [item.output_length_mm for item in plan.label_output[:2]] == [24.5, 24.5]
    assert [item.trim_required for item in plan.label_output] == [True, True, False]
    assert plan.label_output[0].minimum_padding_mm == pytest.approx(
        24.5 - 10 - plan.label_output[0].feed_mm
    )
    assert plan.estimated_mm == pytest.approx(
        plan.leader_mm + sum(item.output_length_mm for item in plan.label_output)
    )
    assert sum(vars(plan.breakdown).values()) == pytest.approx(plan.estimated_mm)
    # The floor applies to the complete cut piece, including configured feed.
    boundary = replace(labels[0], length_mm=24.5 - plan.label_output[0].feed_mm)
    assert backend.plan_batch([boundary]).label_output[0].minimum_padding_mm == 0
    assert backend.plan_batch([replace(boundary, length_mm=boundary.length_mm - 0.5)]).label_output[
        0
    ].minimum_padding_mm == pytest.approx(0.5)
    assert backend.plan_batch([]).label_output == ()
    assert sum(vars(backend.plan_batch([]).breakdown).values()) == 0


@pytest.mark.parametrize("dpi_x", [180, 360])
@pytest.mark.parametrize("cut_each", [True, False])
def test_template_minimum_moves_padding_from_design_to_unused_without_double_charging(
    dpi_x, cut_each
):
    backend = BrotherPTP710BT(object(), feed_mm=4, cut_each=cut_each)
    labels = [
        LabelGeometry(str(i), 12, length, dpi_x, template_padding_mm=padding)
        for i, (length, padding) in enumerate([(10, 4), (10, 3), (40, 0)])
    ]
    plan = backend.plan_batch(labels)
    assert plan.breakdown.design_mm == 53
    assert plan.breakdown.feed_mm == pytest.approx(sum(item.feed_mm for item in plan.label_output))
    assert plan.breakdown.leader_mm == 24.5  # Once for the batch, never per copy.
    assert plan.breakdown.unused_mm == pytest.approx(
        7 + sum(item.minimum_padding_mm for item in plan.label_output)
    )
    assert sum(vars(plan.breakdown).values()) == pytest.approx(plan.estimated_mm)
    unclassified = [replace(label, template_padding_mm=0) for label in labels]
    assert plan.estimated_mm == backend.estimate_consumption(unclassified)


def test_ten_mm_label_with_four_mm_feed_explains_six_point_five_mm_cut_padding():
    backend = BrotherPTP710BT(object(), feed_mm=4)
    plan = backend.plan_batch([LabelGeometry("one", 12, 10, 360)])
    assert plan.breakdown.design_mm == 10
    assert plan.breakdown.feed_mm == pytest.approx(8.0433333333)
    assert plan.breakdown.unused_mm == pytest.approx(6.4566666667)
    assert plan.breakdown.leader_mm == 24.5
    assert plan.estimated_mm == 49


def test_strip_floor_is_applied_once_to_the_complete_strip():
    backend = BrotherPTP710BT(object(), cut_each=False)
    short = LabelGeometry("short", 12, 10)
    single = backend.plan_batch([short])
    assert single.strip_padding_mm > 0
    assert single.label_output[0].minimum_padding_mm == 0
    assert single.label_output[0].trim_required
    assert sum(vars(single.breakdown).values()) == pytest.approx(single.estimated_mm)
    multi = backend.plan_batch([short, replace(short, copy_id="second")])
    assert multi.strip_padding_mm == 0
    assert multi.estimated_mm == pytest.approx(
        multi.leader_mm + sum(item.output_length_mm for item in multi.label_output)
    )


def configure_brother(client):
    definition, production = configured_printer("brother-pt-p710bt", {})
    backend = BrowserPrinter(production)
    definition = replace(definition, id="main", name="Test printer")
    client.app.state.registry.replace(definition, backend)
    worker = client.app.state.fleet.workers["main"]
    worker.backend = backend
    backend.width_mm = 12
    return worker, backend


def short_document():
    return {
        "width_mm": 12,
        "length_mm": 10,
        "auto_length": True,
        "fields": [{"name": "text", "label": "Text", "default": "L1"}],
        "elements": [
            {
                "id": "text",
                "kind": "text",
                "x": 1,
                "y": 2,
                "width": 5,
                "height": 8,
                "auto_width": True,
                "content": "{{text}}",
            }
        ],
    }


def test_individual_preview_submission_and_attempt_save_cut_waste(client, caplog):
    worker, backend = configure_brother(client)
    tape = profile(client, threshold=1, width=12)
    cartridge = install(client, tape["id"])
    template = client.post("/api/templates", json={"name": "Short", "document": short_document()})
    assert template.status_code == 201, template.text
    template = template.json()
    preview = client.post("/api/preview", json={"template_id": template["id"]})
    assert preview.status_code == 200, preview.text
    output = preview.json()["print_plan"]["label_output"][0]
    assert any("10 mm template minimum" in warning for warning in preview.json()["warnings"])
    assert output["design_length_mm"] + output["template_padding_mm"] == 10
    assert output["template_padding_mm"] > 0
    assert sum(preview.json()["print_plan"]["breakdown"].values()) == pytest.approx(
        preview.json()["print_plan"]["estimated_mm"]
    )
    assert output["output_length_mm"] == 24.5
    assert output["trim_required"]
    queued = client.post(
        "/api/jobs",
        json={"template": template["id"], "copies": 2, "tape_profile": tape["id"], "data": {}},
    )
    assert queued.status_code == 201, queued.text
    saved = queued.json()["template_snapshot"]["print_plan"]
    assert queued.json()["template_snapshot"]["warnings"] == preview.json()["warnings"]
    assert len(saved["label_output"]) == 2
    expected = copy.deepcopy(saved)
    group = client.get("/api/queue/groups?copy_state=queued").json()[0]
    assert group["print_plan"]["breakdown"] == saved["breakdown"]
    assert group["print_plan"]["leader_mm"] == 24.5

    # This is durable before the first physical command, even on an uncertain failure.
    def interrupted(labels):
        with client.app.state.factory() as session:
            attempt = session.query(Batch).one()
            assert attempt.print_plan["label_output"][0]["trim_required"]
            assert attempt.print_plan["label_output"][0]["copy_id"] == labels[0].copy_id
        raise PrintInterrupted("Uncertain test print")

    backend.print_batch = interrupted
    worker.tick()
    assert "hand trimming required" in caplog.text
    assert "extra unused tape" in caplog.text
    batches = client.get("/api/batches").json()
    attempt = client.get(f"/api/batches/{batches[0]['id']}").json()
    assert attempt["state"] == "needs_review"
    assert len(attempt["print_plan"]["label_output"]) == 2
    assert attempt["print_plan"]["breakdown"] == saved["breakdown"]
    assert attempt["items"][0]["output_plan"]["minimum_padding_mm"] > 0
    # Changing defaults later cannot rewrite a saved submission or attempt.
    backend.production.cut_each = False
    backend.production.feed_mm = 6
    assert client.get(f"/api/batches/{attempt['id']}").json()["print_plan"] == attempt["print_plan"]
    assert (
        client.get(f"/api/jobs/{queued.json()['id']}").json()["template_snapshot"]["print_plan"]
        == expected
    )
    assert client.get("/api/cartridges").json()[0]["id"] == cartridge["id"]


def test_csv_plan_keeps_mixed_lengths_copies_and_minimum_waste(client):
    worker, backend = configure_brother(client)
    tape = profile(client, width=12)
    template = client.post(
        "/api/templates", json={"name": "Short", "document": short_document()}
    ).json()
    result = client.post(
        "/api/runs/prepare",
        json={
            "name": "Variable labels",
            "request_key": "cut-plan",
            "template": template["id"],
            "expected_revision": template["revision"],
            "tape_profile": tape["id"],
            "csv_text": "Text\nL1\nA much longer label\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 2}, {"source_row": 3, "copies": 1}],
        },
    )
    assert result.status_code == 200, result.text
    run = result.json()["run"]
    plan = run["print_plan"]
    assert any("10 mm template minimum" in warning for warning in run["warnings"])
    short_preview = client.get(f"/api/runs/{run['id']}/rows/0/preview").json()
    assert short_preview["warnings"] == run["warnings"]
    long_preview = client.get(f"/api/runs/{run['id']}/rows/1/preview").json()
    assert not any("10 mm template minimum" in warning for warning in long_preview["warnings"])
    assert [item["trim_required"] for item in plan["label_output"]] == [True, True, False]
    assert plan["estimated_mm"] == pytest.approx(
        plan["leader_mm"] + sum(item["output_length_mm"] for item in plan["label_output"])
    )
    assert sum(plan["breakdown"].values()) == pytest.approx(plan["estimated_mm"])
    install(client, tape["id"])
    submitted = client.post(f"/api/runs/{run['id']}/submit").json()
    queued = client.get("/api/queue/groups?copy_state=queued").json()[0]
    assert queued["print_plan"]["breakdown"] == plan["breakdown"]
    assert queued["print_plan"]["breakdown"]["leader_mm"] == 24.5
    # Only remaining queued copies belong in the live estimate.
    client.delete(f"/api/jobs/{submitted['jobs'][0]['id']}")
    remaining = client.get("/api/queue/groups?copy_state=queued").json()[0]["print_plan"]
    assert len(remaining["label_output"]) == 1
    assert remaining["breakdown"]["unused_mm"] == 0
    assert remaining["breakdown"]["leader_mm"] == 24.5
    backend.production.cut_each = False
    assert client.get(f"/api/runs/{run['id']}").json()["print_plan"] == plan


@pytest.mark.parametrize("measured", [False, True])
def test_successful_attempt_records_source_and_review_preserves_planned_categories(
    client,
    measured,
):
    worker, backend = configure_brother(client)
    if not measured:
        original_print = backend.print_batch

        def print_without_measurement(labels):
            original_print(labels)
            return PrintResult()

        backend.print_batch = print_without_measurement
    tape = profile(client, threshold=1, width=12)
    install(client, tape["id"])
    client.post("/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Test"}})
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    assert batch["consumption_source"] == ("measured" if measured else "estimated")
    assert sum(batch["print_plan"]["breakdown"].values()) == pytest.approx(batch["estimated_mm"])
    backend.fail_after = 0
    client.post("/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Test"}})
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    detail = client.get(f"/api/batches/{batch['id']}").json()
    saved_plan = copy.deepcopy(detail["print_plan"])
    response = client.post(
        f"/api/batches/{batch['id']}/review",
        json={
            "decisions": {item["copy_id"]: "printed" for item in detail["items"]},
            "consumed_mm": 50,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["consumption_source"] == "reported"
    assert response.json()["print_plan"] == saved_plan


def test_migration_preserves_old_attempts_without_inventing_cut_measurements(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "e92b4f06a318")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO batches (id,cartridge_id,state,created_at,estimated_mm,shortage_warning) "
            "VALUES ('old','old','PRINTED',1,50,0)"
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT print_plan FROM batches WHERE id='old'").scalar()
            is None
        )
    command.downgrade(config, "e92b4f06a318")
    assert "print_plan" not in {column["name"] for column in inspect(engine).get_columns("batches")}
    engine.dispose()
