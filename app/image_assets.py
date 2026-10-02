"""Bounded bitmap uploads and a data-only SVG subset, rendered at device resolution."""

import base64
import hashlib
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Any

import resvg_py
from PIL import Image, ImageEnhance, ImageOps

from app.asset_store import AssetStore
from app.identity import LOCAL_OWNER_ID
from app.template_schema import Element

MAX_IMAGE_BYTES = 5_000_000
MAX_PIXELS = 16_000_000
SVG_NS = "http://www.w3.org/2000/svg"
SVG_TAGS = {
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "title",
    "desc",
}
SVG_ATTRIBUTES = set(
    "viewBox width height x y x1 x2 y1 y2 cx cy r rx ry d points transform fill stroke stroke-width stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray stroke-dashoffset fill-rule opacity fill-opacity stroke-opacity preserveAspectRatio".split()
)


def sanitize_svg(data: bytes) -> tuple[bytes, int, int]:
    try:
        source = data.decode("utf-8-sig")
        if "<!" in source or "<?" in source.replace('<?xml version="1.0" encoding="UTF-8"?>', ""):
            raise ValueError(
                "SVG declarations, entities and processing instructions are not supported"
            )
        root = ET.fromstring(source)
        nodes = list(root.iter())
        if len(nodes) > 1000 or len(source) > 200_000:
            raise ValueError("SVG exceeds 1000 elements or 200 KB of markup")
        for node in nodes:
            tag = node.tag.removeprefix(f"{{{SVG_NS}}}")
            if tag not in SVG_TAGS or (node is not root and tag == "svg"):
                raise ValueError(f"Unsupported SVG element: {tag}")
            node.tag = f"{{{SVG_NS}}}{tag}"
            for key, value in node.attrib.items():
                if key not in SVG_ATTRIBUTES or re.search(r"url\s*\(|[<>\\]|@", value, re.I):
                    raise ValueError(f"Unsupported SVG attribute or reference: {key}")
                if len(value) > 100_000:
                    raise ValueError("SVG attribute is too large")
            if tag not in ("title", "desc") and (node.text or "").strip():
                raise ValueError("SVG text must be converted to paths before uploading")
        if root.tag != f"{{{SVG_NS}}}svg":
            raise ValueError("SVG must have an svg root")
        view = root.get("viewBox")
        if view:
            values = [float(v) for v in re.split(r"[\s,]+", view.strip())]
            if len(values) != 4 or not all(
                math.isfinite(v) and abs(v) <= 1_000_000 for v in values
            ):
                raise ValueError("Invalid SVG viewBox")
            width, height = values[2:]
        else:
            width = float(root.get("width", "").removesuffix("px"))
            height = float(root.get("height", "").removesuffix("px"))
            root.set("viewBox", f"0 0 {width} {height}")
        if not all(math.isfinite(v) and 0 < v <= 8192 for v in (width, height)):
            raise ValueError("SVG dimensions must be positive and at most 8192")
        root.set("width", str(width))
        root.set("height", str(height))
        ET.register_namespace("", SVG_NS)
        return ET.tostring(root), max(1, round(width)), max(1, round(height))
    except (ET.ParseError, UnicodeError, OverflowError) as error:
        raise ValueError("Invalid SVG file") from error


class ImageStore(AssetStore):
    suffix = "image"

    def add(self, data: bytes, name: str = "Uploaded image") -> dict[str, Any]:
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Upload an image of at most 5 MB")
        identifier = hashlib.sha256(data).hexdigest()
        if (self.root / f"{identifier}.json").exists():
            return self.metadata(identifier)
        try:
            if data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
                normalized, width, height = sanitize_svg(data)
                kind = "svg"
                # Decode now, so accepted assets are known to be renderable.
                resvg_py.svg_to_bytes(
                    svg_string=normalized.decode(), width=256, height=256, skip_system_fonts=True
                )
            else:
                with Image.open(io.BytesIO(data)) as source:
                    if source.format not in ("PNG", "JPEG", "WEBP", "BMP", "GIF"):
                        raise ValueError("Use PNG, JPEG, WebP, BMP, GIF or a simple SVG")
                    if getattr(source, "n_frames", 1) != 1:
                        raise ValueError("Animated images are not supported; upload a still image")
                    if source.width * source.height > MAX_PIXELS or max(source.size) > 8192:
                        raise ValueError(
                            "Images are limited to 16 megapixels and 8192 pixels per side"
                        )
                    source.load()
                    decoded = ImageOps.exif_transpose(source).convert("RGBA")
                    width, height = decoded.size
                    output = io.BytesIO()
                    decoded.save(output, format="PNG")
                    normalized = output.getvalue()
                    kind = "bitmap"
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("Image could not be decoded") from error
        metadata = {
            "id": identifier,
            "owner_id": LOCAL_OWNER_ID,
            "name": name[:120] or "Uploaded image",
            "kind": kind,
            "width": width,
            "height": height,
            "size_bytes": len(data),
            "archived": False,
        }
        self._write(self.root / f"{identifier}.source", data)
        self._write(self.root / f"{identifier}.image", normalized)
        self._write(self.root / f"{identifier}.json", json.dumps(metadata).encode())
        return metadata


@lru_cache(maxsize=32)
def converted_image(
    path: str,
    width: int,
    height: int,
    brightness: float,
    contrast: float,
    mode: str,
    threshold: int,
) -> str:
    from pathlib import Path

    data = Path(path).read_bytes()
    if data.startswith(b"<"):
        data = resvg_py.svg_to_bytes(
            svg_string=data.decode(), width=width, height=height, skip_system_fonts=True
        )
    with Image.open(io.BytesIO(data)) as source:
        rgba = source.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
    # Transparency exposes tape, and tonal controls affect artwork rather than its background.
    gray = ImageEnhance.Brightness(rgba.convert("L")).enhance(brightness)
    gray = ImageEnhance.Contrast(gray).enhance(contrast)
    paper = Image.new("L", gray.size, 255)
    paper.paste(gray, mask=rgba.getchannel("A"))
    if mode == "dither":
        ink = paper.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        ink = paper.point(lambda value: 255 if value >= threshold else 0, mode="1")
    output = io.BytesIO()
    artwork = ink.convert("RGBA")
    artwork.putalpha(rgba.getchannel("A").point(lambda value: 255 if value else 0))
    artwork.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def image_svg(element: Element, store: ImageStore | None, dpi: int) -> str:
    if store is None or not element.image_asset:
        raise ValueError("Select an uploaded image for this element")
    path = store.path(element.image_asset)
    metadata = store.metadata(element.image_asset)
    width, height = element.width, element.height
    if element.preserve_aspect:
        scale = min(width / metadata["width"], height / metadata["height"])
        width, height = metadata["width"] * scale, metadata["height"] * scale
    pixels = max(1, round(width * dpi / 25.4)), max(1, round(height * dpi / 25.4))
    if pixels[0] * pixels[1] > 2_000_000:
        raise ValueError("Image output exceeds 2 megapixels")
    encoded = converted_image(
        str(path),
        *pixels,
        element.brightness,
        element.contrast,
        element.image_mode,
        element.image_threshold,
    )
    return (
        f'<image x="{(element.width - width) / 2}" y="{(element.height - height) / 2}" '
        f'width="{width}" height="{height}" preserveAspectRatio="none" image-rendering="pixelated" '
        f'href="data:image/png;base64,{encoded}"/>'
    )
