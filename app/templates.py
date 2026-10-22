"""Template persistence and validation, shared by API and job submission."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import LabelTemplate, TemplateRevision, UserGroup
from app.template_schema import TemplateDocument


def seed_templates(session: Session) -> None:
    from app.deletion import is_deleted

    if is_deleted(session, "templates", "text"):
        return
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


def template_record(template: LabelTemplate, session: Session) -> dict[str, Any]:
    group_name = None
    if template.scope == "group" and template.group_id:
        names = session.info.setdefault("template_group_names", {})
        if template.group_id not in names:
            group = session.get(UserGroup, template.group_id)
            names[template.group_id] = group.name if group else None
        group_name = names[template.group_id]
    return {
        "id": template.id,
        "owner_id": template.owner_id,
        "scope": template.scope,
        "group_id": template.group_id,
        "group_name": group_name,
        "name": template.name,
        "revision": template.revision,
        "document": template.document,
        "fields": [f["name"] for f in template.document["fields"]],
        "renderer": "svg",
        "archived": template.archived,
    }
