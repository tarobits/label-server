"""Template persistence and validation, shared by API and job submission."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import LabelTemplate, TemplateRevision
from app.template_schema import TemplateDocument


def seed_templates(session: Session) -> None:
    if session.get(LabelTemplate, "text"):
        return
    document = TemplateDocument.model_validate(
        {
            "width_mm": 24,
            "length_mm": 60,
            "fields": [
                {"name": "text", "label": "Label text", "sample": "Network cables / Box 03"}
            ],
            "elements": [
                {
                    "id": "title",
                    "kind": "text",
                    "x": 2,
                    "y": 2,
                    "width": 56,
                    "height": 20,
                    "content": "{{text}}",
                    "font_size": 3,
                }
            ],
        }
    ).model_dump()
    session.add(
        LabelTemplate(id="text", name="Simple text", scope="global", revision=2, document=document)
    )
    session.flush()
    session.add(
        TemplateRevision(template_id="text", name="Simple text", revision=2, document=document)
    )


def template_record(template: LabelTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "owner_id": template.owner_id,
        "scope": template.scope,
        "group_id": template.group_id,
        "name": template.name,
        "revision": template.revision,
        "document": template.document,
        "fields": [f["name"] for f in template.document["fields"]],
        "renderer": "svg",
        "archived": template.archived,
    }
