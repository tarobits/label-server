"""Fit externally generated artwork to a label using generic render capabilities."""

import math

from app.image_assets import ImageStore
from app.render import RenderSpec, printable_vertical_bounds
from app.schemas import ImageJobInput
from app.template_schema import TemplateDocument


def image_document(
    body: ImageJobInput, tape_width: float, spec: RenderSpec, images: ImageStore
) -> TemplateDocument:
    if spec.media_kind != "continuous":
        raise ValueError("Image submissions currently require continuous media")
    asset = images.metadata(body.image_asset)
    top, bottom = printable_vertical_bounds(tape_width, spec)
    height = bottom - top
    ratio = asset["width"] / asset["height"]
    length = body.length_mm
    if length is None:
        length = max(10, math.ceil((height * ratio + 2 * spec.margin_mm) * 100) / 100)
        if length > 300:
            raise ValueError("Image needs more than 300 mm; specify length_mm to fit it smaller")
    width = length - 2 * spec.margin_mm
    if min(width, height) <= 0:
        raise ValueError("No printable area available for this image")
    image_width = min(width, height * ratio)
    image_height = image_width / ratio
    return TemplateDocument.model_validate(
        {
            "width_mm": tape_width,
            "length_mm": length,
            "print_resolution": body.print_resolution,
            "elements": [
                {
                    "id": "image",
                    "kind": "image",
                    "image_asset": body.image_asset,
                    "x": (length - image_width) / 2,
                    "y": top + (height - image_height) / 2,
                    "width": image_width,
                    "height": image_height,
                    "image_mode": body.image_mode,
                    "image_threshold": body.image_threshold,
                }
            ],
        }
    )
