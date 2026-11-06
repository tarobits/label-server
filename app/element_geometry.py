"""Visible, label-axis geometry over the persisted local-coordinate format."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.template_schema import Element


def element_geometry(element: "Element") -> dict[str, float]:
    width = element.width
    height = element.stroke if element.kind == "line" else element.height
    if element.rotation in (90, 270):
        width, height = height, width
    return {
        "x": element.x + (element.width - width) / 2,
        "y": element.y + (element.height - height) / 2,
        "width": width,
        "height": height,
    }


def local_geometry(geometry: dict[str, float], rotation: int) -> dict[str, float]:
    width, height = geometry["width"], geometry["height"]
    if rotation in (90, 270):
        width, height = height, width
    return {
        "x": geometry["x"] + (geometry["width"] - width) / 2,
        "y": geometry["y"] + (geometry["height"] - height) / 2,
        "width": width,
        "height": height,
    }
