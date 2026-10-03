import base64
import io

import pytest
from conftest import profile
from PIL import Image
from pydantic import ValidationError

from app.render import RenderSpec, element_bounds, render_document
from app.template_schema import TemplateDocument


def cable_document():
    return {
        "auto_length": True,
        "fields": [
            {"name": "left", "label": "Left", "sample": "A"},
            {"name": "right", "label": "Right", "sample": "B"},
        ],
        "elements": [
            {
                "id": "left",
                "kind": "text",
                "x": 2,
                "y": 4,
                "width": 20,
                "height": 8,
                "content": "{{left}}",
                "auto_width": True,
            },
            {
                "id": "divider",
                "kind": "line",
                "x": 25,
                "y": 3,
                "width": 1,
                "height": 14,
                "distance_holder": {"element_id": "left", "gap_mm": 3},
            },
            {
                "id": "right",
                "kind": "text",
                "x": 30,
                "y": 4,
                "width": 20,
                "height": 8,
                "content": "{{right}}",
                "auto_width": True,
                "distance_holder": {"element_id": "divider", "gap_mm": 3},
            },
        ],
    }


def assert_gaps(document):
    by_id = {element.id: element for element in document.elements}
    left, divider, right = [element_bounds(by_id[key]) for key in ("left", "divider", "right")]
    assert divider[0] - left[2] == pytest.approx(3)
    assert right[0] - divider[2] == pytest.approx(3)
    assert all(element.distance_holder is None for element in document.elements)


def test_variable_text_is_measured_before_distance_holders_and_label_length():
    doc = TemplateDocument.model_validate(cable_document())
    short = render_document(doc, {"left": "A", "right": "B"}, RenderSpec()).document
    long = render_document(
        doc, {"left": "Long cable source", "right": "Destination"}, RenderSpec()
    ).document
    assert_gaps(short)
    assert_gaps(long)
    assert long.elements[1].x > short.elements[1].x
    assert long.length_mm > short.length_mm
    assert doc.elements[1].distance_holder is not None
    doc.elements.reverse()
    reversed_layout = render_document(
        doc, {"left": "Long cable source", "right": "Destination"}, RenderSpec()
    ).document
    assert_gaps(reversed_layout)
    assert reversed_layout.length_mm == long.length_mm


@pytest.mark.parametrize("axis", ["horizontal", "vertical"])
def test_rotated_bounds_and_negative_unrotated_origins_can_be_positioned(axis):
    doc = TemplateDocument.model_validate(
        {
            "elements": [
                {
                    "id": "anchor",
                    "kind": "line",
                    "x": -4,
                    "y": 9,
                    "width": 12,
                    "height": 2,
                    "rotation": 90,
                },
                {
                    "id": "follower",
                    "kind": "rectangle",
                    "x": 4,
                    "y": 4,
                    "width": 3,
                    "height": 3,
                    "distance_holder": {"element_id": "anchor", "axis": axis, "gap_mm": 2},
                },
            ]
        }
    )
    output = render_document(doc, {}, RenderSpec()).document
    anchor, follower = [element_bounds(element) for element in output.elements]
    assert anchor == (1, 4, 3, 16)
    assert (
        follower[0 if axis == "horizontal" else 1] - anchor[2 if axis == "horizontal" else 3] == 2
    )


@pytest.mark.parametrize("target", ["right", "missing", "divider"])
def test_distance_holders_reject_cycles_self_links_and_missing_targets(target):
    doc = cable_document()
    doc["elements"][1]["distance_holder"]["element_id"] = target
    with pytest.raises(ValidationError, match="Distance holder"):
        TemplateDocument.model_validate(doc)


def test_csv_freezes_distances_for_each_record_before_later_template_edits(client):
    tape = profile(client)
    doc = cable_document()
    saved = client.post("/api/templates", json={"name": "Cable tags", "document": doc})
    assert saved.status_code == 201, saved.text
    template = saved.json()
    prepared = client.post(
        "/api/runs/prepare",
        json={
            "request_key": "cable-tags",
            "name": "Cable tags",
            "template": template["id"],
            "expected_revision": 1,
            "tape_profile": tape["id"],
            "csv_text": "Left,Right\nA,B\nLong cable source,Destination\n",
            "mapping": {"left": "Left", "right": "Right"},
            "rows": [{"source_row": 2, "copies": 1}, {"source_row": 3, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["valid"], prepared.text
    run = prepared.json()["run"]
    previews = [client.get(f"/api/runs/{run['id']}/rows/{i}/preview").json() for i in range(2)]
    assert previews[1]["length_mm"] > previews[0]["length_mm"]
    doc["elements"][1]["distance_holder"]["gap_mm"] = 8
    assert (
        client.put(
            f"/api/templates/{template['id']}",
            json={
                "name": "Changed",
                "document": doc,
                "expected_revision": 1,
            },
        ).status_code
        == 200
    )
    submitted = client.post(f"/api/runs/{run['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    for i, job in enumerate(submitted.json()["jobs"]):
        frozen = TemplateDocument.model_validate(job["template_snapshot"]["document"])
        assert_gaps(frozen)
        assert frozen.length_mm == previews[i]["length_mm"]
        assert client.get(f"/api/runs/{run['id']}/rows/{i}/preview").json() == previews[i]
        history = client.get(f"/api/jobs/{job['id']}/preview")
        assert history.status_code == 200
        expected = Image.open(io.BytesIO(base64.b64decode(previews[i]["png"].split(",")[1])))
        assert (
            Image.open(io.BytesIO(history.content)).convert("L").tobytes()
            == expected.convert("L").tobytes()
        )
