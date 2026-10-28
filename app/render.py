"""Trusted structured documents -> SVG -> monochrome raster -> colored PNG preview."""

import base64
import io
import math
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Literal

import qrcode
import resvg_py
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from PIL import Image, ImageFont, ImageOps

from app.font_assets import FontStore
from app.image_assets import ImageStore, image_svg
from app.models import LabelCopy, PrintJob
from app.printer.base import RenderedLabel
from app.template_schema import TOKEN, Element, TemplateDocument

FONT_DIR = Path(__file__).parent / "fonts"


@dataclass(frozen=True)
class RenderSpec:
    dpi: int = 180
    margin_mm: float = 1
    printable_widths_mm: dict[str, float] | None = None
    media_kind: Literal["continuous", "fixed_label"] = "continuous"
    # Legacy snapshots use dpi for both axes. X follows label length; Y follows tape width.
    dpi_x: int | None = None
    # Versioned so existing snapshots retain their exact raster geometry.
    stretch_canvas: bool = False
    supported_widths_mm: tuple[float, ...] | None = None

    @property
    def horizontal_dpi(self) -> int:
        return self.dpi_x or self.dpi


@dataclass
class RenderOutput:
    svg: str
    image: Image.Image
    warnings: list[str]
    document: TemplateDocument
    font_files: list[str]
    missing_assets: dict[str, str]
    template_padding_mm: float = 0

    def preview(self, foreground: str, background: str, *, smooth: bool = False) -> str:
        source = self.image.convert("L")
        if smooth:
            # Re-render vector geometry, rather than enlarging thresholded device pixels.
            png = resvg_py.svg_to_bytes(
                svg_string=self.svg,
                zoom=4,
                skip_system_fonts=True,
                font_files=self.font_files,
            )
            source = Image.open(io.BytesIO(png)).convert("L")
        colored = ImageOps.colorize(source, foreground, background)
        output = io.BytesIO()
        colored.save(output, format="PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def resolve_values(
    document: TemplateDocument, data: dict[str, str], samples: bool
) -> dict[str, str]:
    names = {field.name for field in document.fields}
    if set(data) - names:
        raise ValueError("Unknown input fields: " + ", ".join(sorted(set(data) - names)))
    values = {}
    for field in document.fields:
        value = data.get(field.name, (field.sample or field.default) if samples else field.default)
        if len(value) > 2000:
            raise ValueError(f"{field.label}: input exceeds 2000 characters")
        if field.required and not value.strip():
            raise ValueError(f"{field.label} is required")
        values[field.name] = value
    return values


@lru_cache(maxsize=128)
def font_for(size: float, bold: bool, path: str | None = None) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        path or str(FONT_DIR / ("NotoSans-Bold.ttf" if bold else "NotoSans.ttf")), round(size * 100)
    )


@lru_cache(maxsize=128)
def supported_characters(path: str | None = None) -> frozenset[int]:
    with TTFont(path or FONT_DIR / "NotoSans.ttf") as font:
        return frozenset(font.getBestCmap())


def font_path(element: Element, fonts: FontStore | None) -> str | None:
    if element.font == "Noto Sans":
        return None
    if fonts is None:
        raise ValueError("Font asset store is unavailable")
    return str(fonts.path(element.font))


def right_to_left(text: str) -> bool:
    return any(unicodedata.bidirectional(char) in ("R", "AL") for char in text)


def text_clusters(text: str) -> list[str]:
    """Keep accents, variation selectors and joined characters with their base."""
    # Bidirectional runs need whole-run shaping and visual ordering. Keep their
    # joining intact rather than separating letters into isolated SVG chunks.
    if right_to_left(text):
        return [text] if text else []
    clusters: list[str] = []
    for char in text:
        if clusters and (
            unicodedata.category(char).startswith("M")
            or char == "\u200d"
            or clusters[-1].endswith("\u200d")
            or unicodedata.combining(clusters[-1][-1]) == 9  # Virama joins the next consonant.
        ):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def text_advance(font: ImageFont.FreeTypeFont, text: str, spacing: float) -> float:
    # Explicit tracking must separate optional ligatures such as ffi. Preserve
    # normal kerning and the original shaping path when no tracking is requested.
    features = (
        ["-liga", "-clig"]
        if spacing and len(text_clusters(text)) > 1 and font.layout_engine == ImageFont.Layout.RAQM
        else None
    )
    return font.getlength(text, features=features) / 100


def text_width(font: ImageFont.FreeTypeFont, text: str, spacing: float) -> float:
    if not spacing:
        return font.getlength(text) / 100
    return text_advance(font, text, spacing) + max(0, len(text_clusters(text)) - 1) * spacing


def text_svg(element: Element, text: str, fonts: FontStore | None = None) -> str:
    path = font_path(element, fonts)
    family = "Noto Sans" if path is None else f"LabelFont_{element.font[:48]}"
    if any(ord(char) not in supported_characters(path) for char in text if char not in "\n\r\t"):
        raise ValueError("Text contains characters unsupported by the selected font")
    font = font_for(element.font_size, element.bold, path)
    paragraphs = text.replace("\t", "    ").splitlines() or [""]
    ascent, descent = font.getmetrics()
    base_line_height = (ascent + descent) / 100
    inner_width = element.width - element.padding_left - element.padding_right
    inner_height = element.height - element.padding_top - element.padding_bottom
    if inner_width <= 0 or inner_height <= 0:
        raise ValueError(f"Element {element.id}: text padding leaves no space for text")

    def width(line: str, scale: float) -> float:
        return text_width(font, line, element.character_spacing) * scale

    def block_height(count: int) -> float:
        return count * base_line_height + max(0, count - 1) * element.line_spacing

    def layout(scale: float) -> list[str] | None:
        lines: list[str] = []
        for paragraph in paragraphs:
            if not element.wrap:
                if width(paragraph, scale) > inner_width:
                    return None
                lines.append(paragraph)
                continue
            line = ""
            characters = (
                text_clusters(paragraph)
                if element.character_spacing and not right_to_left(paragraph)
                else paragraph
            )
            for char in characters:
                if width(line + char, scale) > inner_width:
                    if not line or width(char, scale) > inner_width:
                        return None
                    lines.append(line)
                    line = char
                else:
                    line += char
            lines.append(line)
        return lines if block_height(len(lines)) * scale <= inner_height else None

    scale = 1.0
    lines = layout(scale)
    if lines is None:
        # Search with continuous font metrics: even tiny boxes can fit without
        # a minimum font-size rejection. The chosen size remains the upper bound.
        low = 0.0
        widest = max((font.getlength(c) / 100 for c in text if c not in "\n\r\t"), default=0)
        high = min(1.0, inner_height / block_height(len(paragraphs)))
        if widest:
            high = min(high, inner_width / widest)
        for _ in range(32):
            middle = (low + high) / 2
            if layout(middle) is None:
                high = middle
            else:
                low = middle
        scale = low
        lines = layout(scale)
        assert lines is not None
    line_height = (base_line_height + element.line_spacing) * scale
    anchor = {"left": "start", "center": "middle", "right": "end"}[element.align]
    x = {"left": 0, "center": inner_width / 2, "right": inner_width}[element.align]
    remaining = max(0, inner_height - block_height(len(lines)) * scale)
    y_offset = {"top": 0, "center": remaining / 2, "bottom": remaining}[element.vertical_align]
    parts = []
    for index, line in enumerate(lines):
        content = escape(line)
        line_anchor = anchor
        if element.character_spacing:
            # resvg tracks shaped clusters and retains optional ligatures. Give
            # each character cluster an explicit origin so measured advances,
            # kerning, accents and physical character gaps match the output.
            line_anchor = "start"
            offset = {"left": 0, "center": -width(line, scale) / 2, "right": -width(line, scale)}[
                element.align
            ]
            prefix = ""
            spans = []
            for position, cluster in enumerate(text_clusters(line)):
                prefix += cluster
                advance = text_advance(font, prefix, element.character_spacing) - text_advance(
                    font, cluster, element.character_spacing
                )
                origin = x + offset + (advance + position * element.character_spacing) * scale
                spans.append(f'<tspan x="{origin}">{escape(cluster)}</tspan>')
            content = "".join(spans)
        parts.append(
            f'<text x="{x}" y="{y_offset + ascent * scale / 100 + index * line_height}" font-family="{family}" font-size="{element.font_size * scale}" font-weight="{700 if element.bold and path is None else 400}" text-anchor="{line_anchor}" xml:space="preserve">{content}</text>'
        )
    body = "".join(parts)
    if any(
        (element.padding_left, element.padding_right, element.padding_top, element.padding_bottom)
    ):
        return (
            f'<svg x="{element.padding_left}" y="{element.padding_top}" '
            f'width="{inner_width}" height="{inner_height}" overflow="hidden">{body}</svg>'
        )
    return body


def qr_svg(element: Element, content: str, spec: RenderSpec) -> str:
    if not content:
        raise ValueError("QR content cannot be empty")
    if len(content.encode("utf-8")) > 1000:
        raise ValueError("QR content exceeds 1000 bytes")
    explicit_margin = element.qr_fill_box and element.qr_margin_mm is not None
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, border=0 if explicit_margin else 4
    )
    qr.add_data(content)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    margin = (element.qr_margin_mm or 0) if explicit_margin else 0
    available = element.width - 2 * margin
    qr_dpi = min(spec.horizontal_dpi, spec.dpi)
    module_pixels = math.floor(available * qr_dpi / 25.4 / len(matrix))
    if module_pixels < 2:
        raise ValueError(
            "QR code is too small: enlarge it or shorten its content (minimum 2 pixels per module)"
        )
    module = module_pixels * 25.4 / qr_dpi
    if element.qr_fill_box:
        # Enlarge into the available area. Never bypass the minimum
        # module size above; old documents retain integer-pixel sizing by default.
        module = max(module, available / len(matrix))
    offset = (element.width - len(matrix) * module) / 2
    cells = [
        f"M{offset + col * module},{offset + row * module}h{module}v{module}h{-module}z"
        for row, values in enumerate(matrix)
        for col, ink in enumerate(values)
        if ink
    ]
    return f'<rect width="{element.width}" height="{element.height}" fill="white"/><path d="{"".join(cells)}" shape-rendering="crispEdges"/>'


def element_bounds(element: Element) -> tuple[float, float, float, float]:
    width, height = (
        (element.height, element.width)
        if element.rotation in (90, 270)
        else (element.width, element.height)
    )
    x = element.x + (element.width - width) / 2
    y = element.y + (element.height - height) / 2
    return x, y, x + width, y + height


def resolve_layout(
    document: TemplateDocument,
    values: dict[str, str],
    spec: RenderSpec,
    fonts: FontStore | None = None,
    warnings: list[str] | None = None,
) -> TemplateDocument:
    resolved = document.model_copy(deep=True)
    for element in resolved.elements:
        if element.kind == "text" and element.auto_width:
            content = TOKEN.sub(lambda match: values[match.group(1)], element.content)
            font = font_for(element.font_size, element.bold, font_path(element, fonts))
            lines = content.replace("\t", "    ").splitlines() or [""]
            # Round outward so floating point measurement never forces an extra wrap.
            element.width = (
                max(
                    0.1,
                    math.ceil(
                        max(text_width(font, line, element.character_spacing) for line in lines)
                        * 100
                    )
                    / 100,
                )
                + element.padding_left
                + element.padding_right
            )
            if element.width > 1000:
                raise ValueError("Automatically sized text exceeds the maximum element width")
            element.auto_width = False
    elements = {element.id: element for element in resolved.elements}
    positioned: set[str] = set()

    def position(element: Element) -> None:
        if element.id in positioned:
            return
        holder = element.distance_holder
        if holder:
            anchor = elements[holder.element_id]
            position(anchor)
            left, top, _, _ = element_bounds(element)
            _, _, right, bottom = element_bounds(anchor)
            if holder.axis == "horizontal":
                element.x += right + holder.gap_mm - left
            else:
                element.y += bottom + holder.gap_mm - top
            if not -1000 <= element.x <= 1000 or not -100 <= element.y <= 100:
                raise ValueError("Distance holder places an element beyond supported coordinates")
            # Freeze the resolved geometry, not a relation that could move an old job later.
            element.distance_holder = None
        positioned.add(element.id)

    for element in resolved.elements:
        position(element)
    if resolved.auto_length:
        if spec.media_kind != "continuous":
            raise ValueError("Automatic label length requires continuous media")
        natural_length = fitted_length(resolved, spec.margin_mm)
        if natural_length < 10 and warnings is not None:
            warnings.append(
                "Automatic length would be below the 10 mm template minimum; "
                "the label is extended to 10 mm."
            )
        resolved.length_mm = max(10, math.ceil(natural_length * 100) / 100)
        if resolved.length_mm > 300:
            raise ValueError("Automatic label length exceeds the 300 mm limit")
        resolved.auto_length = False
    return resolved


def fitted_length(document: TemplateDocument, margin_mm: float) -> float:
    return max(0, max((element_bounds(e)[2] for e in document.elements), default=0) + margin_mm)


def missing_asset_svg(element: Element, kind: str) -> str:
    if kind == "image":
        icon = (
            '<path d="M8 1h11l6 6v16H8zM19 1v6h6" fill="white" '
            'stroke="black" stroke-width="1.2"/>'
            '<text x="16.5" y="19" text-anchor="middle" font-size="13">?</text>'
        )
    else:
        icon = (
            '<text x="1" y="21" font-size="20">Aa</text>'
            '<text x="30" y="8" text-anchor="end" font-size="10">?</text>'
        )
    return (
        f'<svg width="{element.width}" height="{element.height}" viewBox="0 0 32 24" '
        f'font-family="Noto Sans" aria-label="Missing {kind}">{icon}</svg>'
    )


def render_document(
    document: TemplateDocument,
    data: dict[str, str],
    spec: RenderSpec,
    samples: bool = False,
    fonts: FontStore | None = None,
    images: ImageStore | None = None,
    allow_missing_assets: bool = False,
) -> RenderOutput:
    missing: dict[str, str] = {}
    if allow_missing_assets:
        document = document.model_copy(deep=True)
        for element in document.elements:
            try:
                if element.kind == "text":
                    font_path(element, fonts)
                elif element.kind == "image" and element.image_asset:
                    if images is None:
                        raise ValueError("Image library unavailable")
                    images.path(element.image_asset)
            except ValueError:
                missing[element.id] = "font" if element.kind == "text" else "image"
                # Resolve placement using the original box, without substituting font metrics.
                element.kind = "rectangle"
                element.auto_width = False
                element.font = "Noto Sans"
    if spec.supported_widths_mm is not None and document.width_mm not in spec.supported_widths_mm:
        raise ValueError("The selected printer does not support this physical tape width")
    band = (spec.printable_widths_mm or {}).get(f"{document.width_mm:g}")
    vertical_margin = (document.width_mm - band) / 2 if band else spec.margin_mm
    values = resolve_values(document, data, samples)
    layout_warnings: list[str] = []
    automatic_length = document.auto_length
    document = resolve_layout(document, values, spec, fonts, warnings=layout_warnings)
    template_padding = (
        max(0, 10 - fitted_length(document, spec.margin_mm)) if automatic_length else 0
    )
    font_files = [str(FONT_DIR / "NotoSans.ttf"), str(FONT_DIR / "NotoSans-Bold.ttf")]
    font_files.extend(
        sorted(
            {
                path
                for e in document.elements
                if e.kind == "text"
                if (path := font_path(e, fonts)) is not None
            }
        )
    )
    px_width = round(document.length_mm * spec.horizontal_dpi / 25.4)
    px_height = round(document.width_mm * spec.dpi / 25.4)
    aspect = (
        ' preserveAspectRatio="none"'
        if spec.stretch_canvas or spec.horizontal_dpi != spec.dpi
        else ""
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{px_width}" height="{px_height}" viewBox="0 0 {document.length_mm} {document.width_mm}"{aspect}><rect width="100%" height="100%" fill="white"/>'
    ]
    qr_boxes: list[tuple[float, float, float, float, str]] = []
    boxes: list[tuple[float, float, float, float, str]] = []
    warnings: list[str] = [
        f"Missing {kind} in element {identifier}. Restore or replace it before printing."
        for identifier, kind in missing.items()
    ]
    warnings.extend(layout_warnings)
    clipping = document.out_of_bounds == "clip"
    if clipping:
        parts.append(
            f'<defs><clipPath id="printable"><rect x="{spec.margin_mm}" y="{vertical_margin}" '
            f'width="{document.length_mm - 2 * spec.margin_mm}" '
            f'height="{document.width_mm - 2 * vertical_margin}"/></clipPath></defs>'
            '<g clip-path="url(#printable)">'
        )
    for element in document.elements:
        x, y, right, bottom = element_bounds(element)
        outside = (
            x < spec.margin_mm - 0.001
            or y < vertical_margin - 0.001
            or right > document.length_mm - spec.margin_mm + 0.001
            or bottom > document.width_mm - vertical_margin + 0.001
        )
        if outside:
            if not clipping:
                raise ValueError(
                    f"Element {element.id} is outside the printable area ({spec.margin_mm} mm margins)"
                )
            omitted = (
                right <= spec.margin_mm
                or bottom <= vertical_margin
                or x >= document.length_mm - spec.margin_mm
                or y >= document.width_mm - vertical_margin
            )
            warnings.append(
                f"Element {element.id} is {'omitted' if omitted else 'clipped'} at the printable area."
            )
            if omitted:
                continue
        box = (x, y, right, bottom, element.id)
        boxes.append(box)
        content = TOKEN.sub(lambda match: values[match.group(1)], element.content)
        if element.id in missing:
            body = missing_asset_svg(element, missing[element.id])
        elif element.kind == "text":
            body = text_svg(element, content, fonts)
        elif element.kind == "qr":
            qr_boxes.append(box)
            body = qr_svg(element, content, spec)
        elif element.kind == "image":
            body = image_svg(element, images, spec.horizontal_dpi, spec.dpi)
        elif element.kind == "rectangle":
            inset = element.stroke / 2
            body = f'<rect x="{inset}" y="{inset}" width="{element.width - element.stroke}" height="{element.height - element.stroke}" stroke="black" stroke-width="{element.stroke}" fill="{"black" if element.filled else "none"}"/>'
        else:
            body = f'<path d="M0,{element.height / 2}h{element.width}" stroke="black" stroke-width="{element.stroke}"/>'
        parts.append(
            f'<g transform="translate({element.x},{element.y}) rotate({element.rotation},{element.width / 2},{element.height / 2})">{body}</g>'
        )
    if clipping:
        parts.append("</g>")
    for q in qr_boxes:
        for other in boxes:
            if (
                q[4] != other[4]
                and q[0] < other[2]
                and q[2] > other[0]
                and q[1] < other[3]
                and q[3] > other[1]
            ):
                warnings.append(
                    f"QR code {q[4]} has overlapping element bounds. "
                    "Overlap is allowed; check that its modules and clear border remain readable."
                )
                break
    parts.append("</svg>")
    svg = "".join(parts)
    png = resvg_py.svg_to_bytes(
        svg_string=svg,
        skip_system_fonts=True,
        font_files=font_files,
    )
    source = Image.open(io.BytesIO(png)).convert("L")
    image = source.point(lambda value: 255 if value >= 128 else 0, mode="1")
    return RenderOutput(svg, image, warnings, document, font_files, missing, template_padding)


def render_job(
    job: PrintJob,
    copy: LabelCopy,
    fonts: FontStore | None = None,
    images: ImageStore | None = None,
    *,
    allow_missing_assets: bool = False,
) -> RenderedLabel:
    snapshot = job.template_snapshot
    if snapshot.get("renderer") == "mock":
        # Preserve old queued fixture jobs rather than silently changing their output.
        return RenderedLabel(copy.id, job.width_mm, job.length_mm, 8, 8, b"\xaa\x55" * 4)
    spec = RenderSpec(**snapshot["render_spec"])
    output = render_document(
        TemplateDocument.model_validate(snapshot["document"]),
        job.payload,
        spec,
        fonts=fonts,
        images=images,
        allow_missing_assets=allow_missing_assets,
    )
    # Public raster contract: a set bit means ink; Pillow uses a set bit for white.
    ink = ImageOps.invert(output.image.convert("L")).convert("1")
    return RenderedLabel(
        copy.id,
        job.width_mm,
        job.length_mm,
        ink.width,
        ink.height,
        ink.tobytes(),
        dpi_x=spec.horizontal_dpi,
        dpi_y=spec.dpi,
        canvas_width_mm=output.document.width_mm,
        template_padding_mm=snapshot.get("template_padding_mm", output.template_padding_mm),
    )
