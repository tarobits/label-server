import copy

import pytest
from conftest import install, profile
from pydantic import ValidationError
from test_access_security import SVG
from test_access_security import accounts as accounts

from app.logic_engine import resolve_inputs
from app.logic_schema import LogicInput
from app.render import resolve_values
from app.template_schema import TemplateDocument


def document(version=1):
    return {
        "version": version,
        "fields": [
            {
                "name": "caption",
                "label": "Caption",
                "required": False,
                "default": "",
                "sample": "Sample",
                "min_length": 2,
                "max_length": 20,
                **({"type": "text"} if version == 2 else {}),
            }
        ],
        "elements": [
            {
                "id": "title",
                "kind": "text",
                "x": 2,
                "y": 2,
                "width": 45,
                "height": 12,
                "content": "{{caption}}",
                **({"logic_name": "text1"} if version == 2 else {}),
            }
        ],
        "preview_examples": [
            {"id": "short", "name": "Short", "data": {"caption": "Hi"}},
            {"id": "long", "name": "Long", "data": {"caption": "Longer caption"}},
        ],
    }


def test_examples_survive_save_history_restore_and_render_unsaved_changes(client):
    response = client.post("/api/templates", json={"name": "Examples", "document": document()})
    assert response.status_code == 201, response.text
    item = response.json()
    path = f"/api/templates/{item['id']}"
    original = client.get(path).json()
    assert original["document"]["preview_examples"] == document()["preview_examples"]
    unsaved = copy.deepcopy(original["document"])
    unsaved["elements"][0]["font_size"] = 6
    images = []
    for example in unsaved["preview_examples"]:
        preview = client.post("/api/preview", json={"document": unsaved, "data": example["data"]})
        assert preview.status_code == 200, preview.text
        images.append(preview.json()["png"])
    assert images[0] != images[1]
    assert client.get(path).json()["document"] == original["document"]
    unsaved["preview_examples"][0]["data"]["caption"] = "Changed"
    response = client.put(
        path, json={"name": "Examples", "document": unsaved, "expected_revision": item["revision"]}
    )
    assert response.status_code == 200, response.text
    restored = client.post(f"{path}/revisions/1/restore", json={"expected_revision": 2})
    assert restored.status_code == 200, restored.text
    assert (
        restored.json()["document"]["preview_examples"] == original["document"]["preview_examples"]
    )


@pytest.mark.parametrize("version", [1, 2])
def test_text_lengths_enforced_in_previews_and_submissions(client, version):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    response = client.post("/api/templates", json={"name": "Limits", "document": document(version)})
    assert response.status_code == 201, response.text
    template = response.json()["id"]
    for value, status in [("x", 422), ("x" * 21, 422), ("Hi", 200), ("é" * 20, 200), ("", 200)]:
        preview = client.post(
            "/api/preview", json={"template_id": template, "data": {"caption": value}}
        )
        assert preview.status_code == status, preview.text
        job = client.post(
            "/api/jobs",
            json={"template": template, "tape_profile": tape["id"], "data": {"caption": value}},
        )
        assert job.status_code == (201 if status == 200 else status), job.text


def test_length_definition_validation_and_legacy_defaults():
    doc = TemplateDocument.model_validate(document())
    assert resolve_values(doc, {"caption": "😀" * 20}, False)["caption"] == "😀" * 20
    typed = LogicInput(name="caption", label="Caption", max_length=20)
    assert resolve_inputs([typed], {"caption": "😀" * 20})["caption"] == "😀" * 20
    for limits in [{"min_length": 5, "max_length": 2}, {"min_length": -1}, {"max_length": 2001}]:
        raw = document()
        raw["fields"][0].update(limits)
        with pytest.raises(ValidationError):
            TemplateDocument.model_validate(raw)
    with pytest.raises(ValidationError, match="Only text"):
        LogicInput(name="count", label="Count", type="number", min_length=2)
    assert TemplateDocument.model_validate({}).preview_examples == []
    raw = document()
    raw["preview_examples"] *= 2
    with pytest.raises(ValidationError, match="unique"):
        TemplateDocument.model_validate(raw)
    raw = document()
    raw["preview_examples"][0]["data"]["caption"] = "x" * 2001
    with pytest.raises(ValidationError, match="2000"):
        TemplateDocument.model_validate(raw)


def test_example_images_obey_asset_permissions(accounts):
    _, alice, bob = accounts
    uploaded = alice.post(
        "/api/image-assets?name=private.svg", content=SVG, headers={"Content-Type": "image/svg+xml"}
    )
    assert uploaded.status_code == 201, uploaded.text
    raw = document()
    raw["preview_examples"][0]["data"]["photo"] = {"image_asset": uploaded.json()["id"]}
    denied = bob.post("/api/templates", json={"name": "Examples", "document": raw})
    assert denied.status_code == 403, denied.text
