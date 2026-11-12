"""Hide restricted inventory identities in personal activity snapshots."""

import copy
from typing import Any

from app.authn.access import AccessContext


def personal_printer_change(context: AccessContext, change: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(change)
    for key in ("source", "target", "previous_assignment"):
        destination = result.get(key)
        if destination and not context.can_printer(destination.get("id", ""), "view"):
            result[key] = {"id": "", "name": "Restricted printer"}
            if key in ("source", "target"):
                result[f"{key}_id"] = ""
    return result


def personal_attribution(context: AccessContext, attribution: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(attribution)
    if "destination_changes" in result:
        result["destination_changes"] = [
            personal_printer_change(context, change) for change in result["destination_changes"]
        ]
    return result
