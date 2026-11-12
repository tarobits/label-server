"""Typed template resolution, frozen submissions, and image permission boundaries."""

import pytest
from conftest import install, profile
from pydantic import ValidationError
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_image_jobs import upload

from app.models import LabelCopy, PrintJob, Role
from app.printing.submissions import input_fingerprint
from app.render import RenderSpec, render_document, render_job
from app.templates.logic_source import compile_source
from app.templates.template_dimensions import template_dimensions
from app.templates.template_logic import logic_fields, logic_targets
from app.templates.template_schema import TemplateDocument

accounts = account_fixture


def document(source=None, *, automatic=False, image=False):
    raw = {
        "version": 2,
        "width_mm": 24,
        "length_mm": 60,
        "auto_length": automatic,
        "fields": [
            {
                "name": "variable1",
                "label": "Subtitle",
                "type": "text",
                "required": False,
                "default": "",
            },
            {
                "name": "quantity",
                "label": "Quantity",
                "type": "number",
                "default": 3,
                "minimum": 0,
                "maximum": 20,
            },
            {"name": "enabled", "label": "Enabled", "type": "boolean", "default": True},
            {"name": "photo", "label": "Photo", "type": "image", "required": False},
        ],
        "elements": [
            {
                "id": "title-id",
                "logic_name": "text1",
                "kind": "text",
                "x": 2,
                "y": 2,
                "width": 20,
                "height": 14,
                "content": "{{quantity}} / {{enabled}}",
            },
            {
                "id": "subtitle-id",
                "logic_name": "text2",
                "kind": "text",
                "x": 2,
                "y": 16,
                "width": 35,
                "height": 2,
                "content": "{{variable1}}",
            },
        ],
    }
    if image:
        raw["elements"] = [
            {
                "id": "image-id",
                "logic_name": "picture",
                "kind": "image",
                "x": 2,
                "y": 2,
                "width": 10,
                "height": 10,
                "visible": False,
            }
        ]
    if source is None:
        source = (
            "picture.image_asset = photo; picture.visible = filled(photo);"
            if image
            else "let hasSubtitle = filled(variable1); text1.height = if(hasSubtitle, 12, 14); text2.visible = hasSubtitle and enabled;"
        )
    base = TemplateDocument.model_validate(raw)
    raw["logic"] = compile_source(source, logic_fields(base), logic_targets(base)).model_dump()
    return TemplateDocument.model_validate(raw)


def save_template(client, doc):
    response = client.post(
        "/api/templates",
        json={
            "name": "Conditional layout",
            "scope": "global",
            "document": doc.model_dump(mode="json"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("subtitle,height,length", [("", 14, 23), ("Present", 12, 38)])
def test_final_automatic_length_follows_logic_and_never_mutates_template(subtitle, height, length):
    doc = document(automatic=True)
    before = doc.model_dump_json()
    result = render_document(doc, {"variable1": subtitle}, RenderSpec())
    assert result.document.elements[0].height == height
    assert result.document.elements[1].visible is bool(subtitle)
    assert result.document.length_mm == length
    assert result.document.logic is None
    assert result.document.auto_length is False
    assert all(element.literal_content for element in result.document.elements)
    assert result.resolved_inputs is not None
    assert result.resolved_inputs["quantity"] == 3
    assert result.document.elements[0].content == "3 / true"
    assert doc.model_dump_json() == before
    repeated = render_document(result.document, result.resolved_inputs, RenderSpec())
    assert result.image.tobytes() == repeated.image.tobytes()
    assert template_dimensions(doc)["variable_length"] is True


def test_label_length_binding_and_validation():
    doc = document("label.length_mm = max(40, quantity * 12);")
    assert render_document(doc, {"quantity": 5}, RenderSpec()).document.length_mm == 60
    assert template_dimensions(doc) == {"variable_length": True, "length_mm": None}
    with pytest.raises(ValueError, match="automatic label length"):
        document("label.length_mm = 60;", automatic=True)
    for value in (0, 9, 301):
        with pytest.raises(ValueError):
            render_document(document(f"label.length_mm = {value};"), {}, RenderSpec())
    with pytest.raises(ValueError, match="continuous"):
        render_document(document(automatic=True), {}, RenderSpec(media_kind="fixed_label"))


def test_text_binding_is_literal_and_intermediate_tokens_are_supported():
    doc = document('let caption = if(enabled, "Yes", "No"); text2.visible = false;')
    raw = doc.model_dump()
    raw["elements"][0]["content"] = "{{caption}}"
    output = render_document(TemplateDocument.model_validate(raw), {}, RenderSpec())
    assert output.document.elements[0].content == "Yes"
    bound = document("text1.content = variable1; text2.visible = false;")
    result = render_document(bound, {"variable1": "{{not_a_variable}}"}, RenderSpec())
    assert result.document.elements[0].content == "{{not_a_variable}}"
    assert result.resolved_inputs is not None
    assert render_document(result.document, result.resolved_inputs, RenderSpec()).svg == result.svg


def test_hidden_distance_holder_chain_collapses_extent_and_outgoing_gap():
    raw = document("text1.visible = false; text2.visible = false;", automatic=True).model_dump()
    raw["elements"][1]["distance_holder"] = {
        "element_id": "title-id",
        "axis": "horizontal",
        "gap_mm": 8,
    }
    raw["elements"].append(
        {
            "id": "tail-id",
            "logic_name": "tail",
            "kind": "rectangle",
            "x": 2,
            "y": 2,
            "width": 10,
            "height": 4,
            "distance_holder": {"element_id": "subtitle-id", "axis": "horizontal", "gap_mm": 8},
        }
    )
    result = render_document(TemplateDocument.model_validate(raw), {}, RenderSpec())
    assert [element.x for element in result.document.elements] == [2, 2, 2]
    assert result.document.length_mm == 13
    assert all(element.distance_holder is None for element in result.document.elements)


def test_hidden_missing_images_do_not_render_or_extend_length():
    raw = document("", image=True, automatic=True).model_dump()
    raw["elements"][0].update({"image_asset": "a" * 64, "x": 500})
    result = render_document(TemplateDocument.model_validate(raw), {}, RenderSpec())
    assert result.document.length_mm == 10
    assert result.missing_assets == {}


@pytest.mark.parametrize(
    "source",
    [
        "text1.height = 0;",
        "text1.width = 2000;",
        "text1.font_size = 30;",
        "text1.rotation = 45;",
        'text1.align = "invalid";',
    ],
)
def test_bound_properties_still_obey_geometry_constraints(source):
    with pytest.raises(ValueError):
        render_document(document(source), {}, RenderSpec())


def test_image_inputs_cannot_be_interpolated_as_text():
    raw = document().model_dump()
    raw["elements"][0]["content"] = "{{photo}}"
    with pytest.raises(ValueError, match="Image variables"):
        TemplateDocument.model_validate(raw)


def test_v1_rejects_logic_and_typed_inputs_and_still_accepts_legacy_names():
    raw = document().model_dump()
    raw["version"] = 1
    with pytest.raises(ValidationError, match="version 2"):
        TemplateDocument.model_validate(raw)
    legacy = TemplateDocument.model_validate(
        {"fields": [{"name": "label", "label": "Label", "default": "Legacy"}]}
    )
    render_document(legacy, {}, RenderSpec())


def test_direct_submission_freezes_values_geometry_and_retries(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    template = save_template(client, document(automatic=True))
    body = {
        "template": template["id"],
        "tape_profile": tape["id"],
        "copies": 2,
        "data": {"quantity": 0, "enabled": False},
    }
    preview = client.post(
        "/api/preview", json={"template_id": template["id"], "data": body["data"]}
    )
    assert preview.status_code == 200, preview.text
    response = client.post("/api/jobs", json=body, headers={"Idempotency-Key": "typed-example"})
    assert response.status_code == 201, response.text
    submitted = response.json()
    assert submitted["length_mm"] == preview.json()["length_mm"]
    assert submitted["payload"] == {"variable1": "", "quantity": 0, "enabled": False, "photo": None}
    assert submitted["template_snapshot"]["document"]["logic"] is None
    assert submitted["fields"][1]["value"] == "0"
    changed = document('text1.height = 2; text1.content = "Changed";').model_dump()
    update = client.put(
        f"/api/templates/{template['id']}",
        json={
            "name": "Edited",
            "scope": "global",
            "document": changed,
            "expected_revision": template["revision"],
        },
    )
    assert update.status_code == 200, update.text
    assert (
        client.post("/api/jobs", json=body, headers={"Idempotency-Key": "typed-example"}).json()[
            "id"
        ]
        == submitted["id"]
    )
    with client.app.state.factory() as session:
        frozen = session.get(PrintJob, submitted["id"])
        copy_row = session.scalar(select(LabelCopy).where(LabelCopy.job_id == frozen.id))
        expected = render_job(
            frozen, copy_row, client.app.state.fonts, client.app.state.images
        ).raster
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review",
            json={
                "decisions": {copy["id"]: "queued" for copy in submitted["labels"]},
                "consumed_mm": 0,
            },
        ).status_code
        == 200
    )
    worker.backend.fail_after = None
    worker.tick()
    assert all(label.raster == expected for label in worker.backend.batches[-1])


def test_image_input_permissions_preview_submission_requests_and_retention(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    template = save_template(admin, document(image=True))
    image, _ = upload(alice)
    data = {"photo": {"image_asset": image}}
    for actor, expected in ((alice, 200), (bob, 403)):
        response = actor.post("/api/preview", json={"template_id": template["id"], "data": data})
        assert response.status_code == expected, response.text
    # Grant printing so direct-submission failures exercise image authorization.
    with admin.app.state.factory.begin() as session:
        for owner in ("alice", "bob"):
            session.get(Role, f"{owner}-access").permissions = [
                {"kind": "destination", "destination_id": "main", "level": "print"}
            ]
    for route in ("/api/jobs", "/api/requests"):
        with admin.app.state.factory.begin() as session:
            session.get(Role, "bob-access").permissions = [
                {
                    "kind": "destination",
                    "destination_id": "main",
                    "level": "request" if route.endswith("requests") else "print",
                }
            ]
        body = {"template": template["id"], "tape_profile": tape["id"], "data": data}
        payload = {"kind": "job", "input": body} if route.endswith("requests") else body
        assert bob.post(route, json=payload).status_code == 403
    direct = alice.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": data}
    )
    assert direct.status_code == 201, direct.text
    assert direct.json()["template_snapshot"]["document"]["elements"][0]["image_asset"] == image
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "request"}
        ]
    request = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {"template": template["id"], "tape_profile": tape["id"], "data": data},
        },
    )
    assert request.status_code == 201, request.text
    frozen = request.json()["labels"][0]["template_snapshot"]["document"]
    assert frozen["elements"][0]["image_asset"] == image
    assert frozen["logic"] is None
    approved = admin.post(
        f"/api/requests/{request.json()['id']}/approve", json={"expected_revision": 1}
    )
    assert approved.status_code == 200, approved.text
    job = alice.get(f"/api/jobs/{approved.json()['job_ids'][0]}").json()
    assert job["owner_id"] == "alice"
    assert job["fields"][-1]["value"] == "Uploaded image"
    assert alice.delete(f"/api/image-assets/{image}/permanent").status_code == 409


def test_csv_typed_conversion_row_errors_and_frozen_submission(client):
    tape = profile(client)
    template = save_template(client, document(automatic=True))
    body = {
        "request_key": "typed-csv",
        "name": "Typed CSV",
        "template": template["id"],
        "expected_revision": template["revision"],
        "tape_profile": tape["id"],
        "csv_text": "Title,Count,Enabled\nOne,2,true\nTwo,0,false",
        "mapping": {"variable1": "Title", "quantity": "Count", "enabled": "Enabled"},
        "rows": [{"source_row": 2}, {"source_row": 3}],
    }
    response = client.post("/api/runs/prepare", json=body)
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert [row["length_mm"] for row in run["rows"]] == [38, 23]
    assert run["rows"][1]["payload"]["quantity"] == 0
    submitted = client.post(f"/api/runs/{run['id']}/submit").json()
    assert all(job["template_snapshot"]["document"]["logic"] is None for job in submitted["jobs"])
    invalid = {
        **body,
        "request_key": "invalid-csv",
        "csv_text": "Title,Count,Enabled\nOne,not-a-number,true\nTwo,0,maybe",
    }
    result = client.post("/api/runs/prepare", json=invalid).json()
    assert result["valid"] is False
    assert [row["source_row"] for row in result["errors"]] == [2, 3]


def test_csv_image_mapping_is_explicit_and_authorized(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    template = save_template(admin, document(image=True))
    image, _ = upload(alice)
    body = {
        "request_key": "images",
        "name": "Images",
        "template": template["id"],
        "expected_revision": template["revision"],
        "tape_profile": tape["id"],
        "csv_text": "Photo\nportrait.png",
        "mapping": {"photo": "Photo"},
        "rows": [{"source_row": 2}],
        "image_mapping": {"photo": {"portrait.png": {"image_asset": image}}},
    }
    assert bob.post("/api/runs/prepare", json=body).status_code == 403
    allowed = alice.post("/api/runs/prepare", json=body)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["valid"] is True
    request = alice.post(
        "/api/requests", json={"kind": "run", "run_id": allowed.json()["run"]["id"]}
    )
    assert request.status_code == 201, request.text
    assert (
        admin.post(
            f"/api/requests/{request.json()['id']}/approve", json={"expected_revision": 1}
        ).status_code
        == 200
    )
    absent = alice.post(
        "/api/runs/prepare", json={**body, "request_key": "missing-map", "image_mapping": {}}
    ).json()
    assert absent["valid"] is False and absent["errors"][0]["source_row"] == 2


def test_empty_image_mapping_preserves_existing_run_receipts():
    assert input_fingerprint({"request_key": "old"}) == input_fingerprint(
        {"request_key": "old", "image_mapping": {}}
    )


def test_logic_inspection_catalog_sample_errors_and_editor_metadata(client):
    raw = document().model_dump(mode="json")
    raw["logic_editor"] = {
        "version": 1,
        "nodes": [
            {"id": "draft", "kind": "literal", "x": 10, "y": 20, "type": "number", "value": 12}
        ],
    }
    response = client.post("/api/logic/inspect", json=raw)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["targets"]["label"]["properties"] == {"length_mm": "number"}
    assert result["types"]["hasSubtitle"] == "boolean"
    assert result["values"]["quantity"] == 3
    assert {operation["name"] for operation in result["operations"]} >= {"if", "filled", "add"}
    resolved = render_document(TemplateDocument.model_validate(raw), {}, RenderSpec())
    assert resolved.document.logic_editor is None
    raw["fields"][1]["default"] = None
    response = client.post("/api/logic/inspect", json=raw)
    assert response.status_code == 200
    assert response.json()["sample_error"] == "Quantity is required"
    raw["logic_editor"]["nodes"][0]["value"] = 1e20
    assert client.post("/api/logic/inspect", json=raw).status_code == 422


def test_logic_inspection_authorizes_images_in_detached_editor_nodes(accounts):
    _, alice, bob = accounts
    image, _ = upload(alice)
    raw = document().model_dump(mode="json")
    raw["logic_editor"] = {
        "nodes": [
            {
                "id": "draft",
                "kind": "literal",
                "x": 0,
                "y": 0,
                "type": "image",
                "value": {"image_asset": image},
            }
        ]
    }
    assert alice.post("/api/logic/inspect", json=raw).status_code == 200
    assert bob.post("/api/logic/inspect", json=raw).status_code == 403
