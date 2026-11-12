from dataclasses import replace

import pytest
from conftest import install, profile
from pydantic import ValidationError

from app.media import MediaProperties
from app.models import PrintJob
from app.printer.registry import MediaKind
from app.render import RenderSpec, render_document
from app.templates.template_schema import TemplateDocument


def fixed_profile(client, length=40):
    response = client.post(
        "/api/tape-profiles",
        json={
            "name": "Fixed labels",
            "width_mm": 24,
            "media_family": "fixed_label",
            "label_length_mm": length,
            "auto_print_threshold": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def fixed_document(length=40):
    return TemplateDocument(
        width_mm=24,
        length_mm=length,
        media=MediaProperties(media_family="fixed_label", label_length_mm=length),
    )


def fixed_printer(client):
    registry = client.app.state.registry
    original = registry.definition("main")
    registry.replace(
        replace(
            original,
            capabilities=replace(
                original.capabilities,
                media_kind=MediaKind.FIXED_LABEL,
                media_family="fixed_label",
                fixed_label_sizes_mm=((24, 40),),
            ),
        ),
        registry.backend("main"),
    )


@pytest.mark.parametrize(
    "body",
    [
        {"media_family": "unknown"},
        {"media_family": "fixed_label"},
        {"media_family": "tze", "label_length_mm": 40},
        {"media_family": "fixed_label", "label_length_mm": 0},
    ],
)
def test_profile_media_rejects_invalid_properties(client, body):
    assert (
        client.post(
            "/api/tape-profiles", json={"name": "Invalid", "width_mm": 24, **body}
        ).status_code
        == 422
    )


def test_same_width_does_not_make_fixed_labels_compatible_with_tze(client):
    stock = fixed_profile(client)
    cartridge = client.post(
        "/api/cartridges",
        json={
            "profile_id": stock["id"],
            "name": "Fixed-label cartridge",
            "nominal_length_mm": 8000,
        },
    ).json()
    response = client.put("/api/printer/active-tape", json={"cartridge_id": cartridge["id"]})
    assert response.status_code == 422
    assert "media family" in response.text
    assert client.get("/api/status").json()["active_cartridge_id"] is None
    assert (
        client.post(
            "/api/jobs", json={"tape_profile": stock["id"], "data": {"text": "Wrong stock"}}
        ).status_code
        == 422
    )
    with pytest.raises(ValueError, match="media family"):
        render_document(fixed_document(), {}, RenderSpec())


def test_fixed_size_is_exact_and_automatic_length_is_not_allowed():
    spec = RenderSpec(
        media_family="fixed_label",
        media_kind="fixed_label",
        fixed_label_sizes_mm=((24, 40),),
        supported_widths_mm=(24,),
    )
    assert render_document(fixed_document(), {}, spec).document.length_mm == 40
    with pytest.raises(ValueError, match="fixed-label size"):
        render_document(fixed_document(50), {}, spec)
    with pytest.raises(ValidationError, match="stock length"):
        TemplateDocument.model_validate({**fixed_document().model_dump(), "length_mm": 41})
    with pytest.raises(ValidationError, match="continuous media"):
        TemplateDocument.model_validate({**fixed_document().model_dump(), "auto_length": True})


def test_used_profile_media_cannot_change(client):
    stock = profile(client)
    install(client, stock["id"])
    response = client.put(
        f"/api/tape-profiles/{stock['id']}",
        json={
            "name": stock["name"],
            "width_mm": 24,
            "media_family": "fixed_label",
            "label_length_mm": 40,
        },
    )
    assert response.status_code == 409
    assert client.get("/api/tape-profiles").json()[0]["media_family"] == "tze"


def test_fixed_media_survives_preview_submission_and_dispatch(client):
    fixed_printer(client)
    stock = fixed_profile(client)
    install(client, stock["id"])
    response = client.post(
        "/api/templates", json={"name": "Fixed design", "document": fixed_document().model_dump()}
    )
    assert response.status_code == 201, response.text
    template = response.json()
    assert client.get(f"/api/templates/{template['id']}/preview.webp").status_code == 200
    response = client.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": stock["id"], "data": {}}
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["template_snapshot"]["document"]["media"] == {
        "media_family": "fixed_label",
        "label_length_mm": 40,
    }
    client.app.state.fleet.workers["main"].tick()
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "printed"


def test_queued_jobs_recheck_media_even_at_direct_destinations(client):
    stock = profile(client, threshold=1)
    install(client, stock["id"])
    response = client.post(
        "/api/jobs", json={"tape_profile": stock["id"], "data": {"text": "Queued TZe"}}
    )
    assert response.status_code == 201
    job = response.json()
    fixed_printer(client)
    with client.app.state.factory() as session:
        assert not client.app.state.fleet.supports_geometry(
            session.get(PrintJob, job["id"]), "main"
        )
    client.app.state.fleet.workers["main"].tick()
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "queued"


def test_media_upgrade_keeps_legacy_profiles_as_tze(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.db import make_engine

    url = f"sqlite:///{tmp_path / 'media.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "131314a58ba1")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tape_profiles (id, name, width_mm, foreground, background, auto_print_threshold, waiting_notification_enabled, waiting_notification_interval_seconds, reminder_silenced, reminder_episode, reminder_active) VALUES ('legacy', 'Legacy', 24, '#000000', '#ffffff', 10, 0, 86400, 0, 0, 0)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT media_family, label_length_mm FROM tape_profiles WHERE id='legacy'")
        ).one() == ("tze", None)
    engine.dispose()
