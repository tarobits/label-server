"""Trusted structured documents -> SVG -> monochrome raster -> colored PNG preview."""

import base64
import io
import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Literal

import qrcode
import qrcode.constants
import resvg_py
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from PIL import Image, ImageFont, ImageOps

from app.assets.asset_cache import using_cache
from app.assets.font_assets import FontStore
from app.assets.font_variations import InvalidFontWeight, static_instance
from app.assets.image_assets import ImageStore, image_svg
from app.barcodes import encode_barcode, encode_matrix
from app.i18n import Message
from app.models import LabelCopy, PrintJob
from app.printer.base import RenderedLabel
from app.templates.element_geometry import element_geometry
from app.templates.logic_schema import Value, check_text_length
from app.templates.template_schema import TOKEN, Element, TemplateDocument, TemplateField

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
    # Keep old job snapshots unchanged; new renders align the band to whole device rows.
    align_printable_band: bool = False
    media_family: str = "tze"
    fixed_label_sizes_mm: tuple[tuple[float, float], ...] = ()

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
    resolved_inputs: dict[str, Value] | None = None
    font_store: FontStore | None = None

    @using_cache
    def preview(self, foreground: str, background: str, *, smooth: bool = False) -> str:
        source = self.image.convert("L")
        if smooth:
            # A retained output may outlive the idle cache timeout.
            if self.font_store:
                self.font_files = [
                    str(FONT_DIR / "NotoSans.ttf"),
                    str(FONT_DIR / "NotoSans-Bold.ttf"),
                ]
                self.font_files.extend(
                    sorted(
                        {
                            path
                            for element in self.document.elements
                            if element.kind == "text" and element.visible
                            if (path := font_path(element, self.font_store)) is not None
                        }
                    )
                )
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
    document: TemplateDocument, data: Mapping[str, object], samples: bool
) -> dict[str, str]:
    names = {field.name for field in document.fields}
    if set(data) - names:
        raise ValueError("Unknown input fields: " + ", ".join(sorted(set(data) - names)))
    values = {}
    for field in document.fields:
        if not isinstance(field, TemplateField):
            raise ValueError(Message("domainMessages.typedInputsRequireVersion2LogicResolution"))
        value = data.get(field.name, (field.sample or field.default) if samples else field.default)
        if not isinstance(value, str):
            raise ValueError(Message("logicErrors.value1ExpectedText", value1=field.label))
        if len(value) > 2000:
            raise ValueError(
                Message("logicErrors.value1InputExceeds2000Characters", value1=field.label)
            )
        check_text_length(value, field.min_length, field.max_length, field.label)
        if field.required and not value.strip():
            raise ValueError(Message("logicErrors.value1IsRequired", value1=field.label))
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
        return frozenset(font.getBestCmap() or {})


def font_path(element: Element, fonts: FontStore | None) -> str | None:
    if element.font == "Noto Sans":
        if element.font_weight is None:
            return None
        if not 100 <= element.font_weight <= 900:
            raise InvalidFontWeight("Noto Sans weight must be between 100 and 900")
        source = FONT_DIR / (
            "NotoSans.ttf"
            if element.font_weight == 400
            else "NotoSans-Bold.ttf"
            if element.font_weight == 700
            else "NotoSans-Variable.ttf"
        )
        return str(static_instance(source, element.font_weight, fonts.root if fonts else None))
    if fonts is None:
        raise ValueError(Message("domainMessages.fontAssetStoreIsUnavailable"))
    source = fonts.path(element.font)
    with TTFont(source) as font:
        variable = "fvar" in font
    if variable or element.font_weight is not None:
        return str(static_instance(source, element.font_weight, fonts.root))
    return str(source)


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


def text_block_height(font: ImageFont.FreeTypeFont, count: int, spacing: float) -> float:
    ascent, descent = font.getmetrics()
    base_line_height = (ascent + descent) / 100
    return count * base_line_height + max(0, count - 1) * spacing


def text_svg(element: Element, text: str, fonts: FontStore | None = None) -> str:
    path = font_path(element, fonts)
    if path is None:
        family = "Noto Sans"
    elif Path(path).stem.startswith("LabelWeight_"):
        family = Path(path).stem
    else:
        family = f"LabelFont_{element.font[:48]}"
    if any(ord(char) not in supported_characters(path) for char in text if char not in "\n\r\t"):
        raise ValueError(
            Message("domainMessages.textContainsCharactersUnsupportedByTheSelectedFont")
        )
    font = font_for(element.font_size, element.bold, path)
    paragraphs = text.replace("\t", "    ").splitlines() or [""]
    ascent, descent = font.getmetrics()
    base_line_height = (ascent + descent) / 100
    inner_width = element.width - element.padding_left - element.padding_right
    inner_height = element.height - element.padding_top - element.padding_bottom
    if inner_width <= 0 or inner_height <= 0:
        raise ValueError(
            Message("logicErrors.elementValue1TextPaddingLeavesNoSpaceForText", value1=element.id)
        )

    def width(line: str, scale: float) -> float:
        return text_width(font, line, element.character_spacing) * scale

    def block_height(count: int) -> float:
        return text_block_height(font, count, element.line_spacing)

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


def matrix_svg(element: Element, content: str, spec: RenderSpec) -> str:
    matrix = encode_matrix(element.kind, content)
    rows, columns = len(matrix), len(matrix[0])
    # An additional clear module on all sides also protects Aztec symbols,
    # whose encoder need not supply a quiet zone.
    dpi = min(spec.dpi, spec.horizontal_dpi)
    pixels = math.floor(
        min(element.width / (columns + 2), element.height / (rows + 2)) * dpi / 25.4
    )
    if pixels < 2:
        raise ValueError(
            Message(
                "domainMessages.matrixCodeIsTooSmallEnlargeItOrShortenItsContentMinimum2PixelsPerModule"
            )
        )
    module = pixels * 25.4 / dpi
    x, y = (element.width - columns * module) / 2, (element.height - rows * module) / 2
    cells = "".join(
        f"M{x + column * module},{y + row * module}h{module}v{module}h{-module}z"
        for row, values in enumerate(matrix)
        for column, ink in enumerate(values)
        if ink
    )
    return f'<path d="{cells}" fill="black"/>'


def barcode_svg(element: Element, content: str, spec: RenderSpec, fonts: FontStore | None) -> str:
    pattern, caption = encode_barcode(element.barcode_format, content)
    # Keep quiet zones inside the element box. Use whole printer pixels per
    # module, with the horizontal physical axis following element rotation.
    dpi = spec.dpi if element.rotation % 180 else spec.horizontal_dpi
    quiet = 11 if element.barcode_format.startswith("ean") else 10
    pixels = math.floor(element.width * dpi / 25.4 / (len(pattern) + quiet * 2))
    if pixels < 2:
        raise ValueError(
            Message(
                "domainMessages.barcodeIsTooNarrowWidenItOrShortenItsContentMinimum2PixelsPerModule"
            )
        )
    module = pixels * 25.4 / dpi
    offset = (element.width - len(pattern) * module) / 2
    caption_height = element.font_size + 1 if element.barcode_caption else 0
    height = element.height - caption_height
    if height < 3:
        raise ValueError(
            Message("domainMessages.barcodeIsTooShortAllowAtLeast3MmForBarsPlusSpaceForItsCaption")
        )
    bars = "".join(
        f"M{offset + i * module},0h{module}v{height}h{-module}z"
        for i, bit in enumerate(pattern)
        if bit == "1"
    )
    body = f'<path d="{bars}" fill="black"/>'
    if element.barcode_caption:
        text = Element(
            id="barcode-caption",
            kind="text",
            x=0,
            y=0,
            width=element.width,
            height=element.font_size,
            font_size=element.font_size,
            align="center",
            vertical_align="center",
            wrap=False,
        )
        body += f'<g transform="translate(0,{height + 1})">{text_svg(text, caption, fonts)}</g>'
    return body


def qr_svg(element: Element, content: str, spec: RenderSpec) -> str:
    if not content:
        raise ValueError(Message("domainMessages.qrContentCannotBeEmpty"))
    if len(content.encode("utf-8")) > 1000:
        raise ValueError(Message("domainMessages.qrContentExceeds1000Bytes"))
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
            Message(
                "domainMessages.qrCodeIsTooSmallEnlargeItOrShortenItsContentMinimum2PixelsPerModule"
            )
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
    if not element.visible:
        return element.x, element.y, element.x, element.y
    geometry = element_geometry(element)
    x, y = geometry["x"], geometry["y"]
    return x, y, x + geometry["width"], y + geometry["height"]


@using_cache
def resolve_layout(
    document: TemplateDocument,
    values: dict[str, str],
    spec: RenderSpec,
    fonts: FontStore | None = None,
    warnings: list[str] | None = None,
    *,
    measure_hidden: bool = False,
) -> TemplateDocument:
    resolved = document.model_copy(deep=True)
    for element in resolved.elements:
        if (element.visible or measure_hidden) and element.kind == "text" and element.auto_width:
            content = (
                element.content
                if element.literal_content
                else TOKEN.sub(lambda match: values[match.group(1)], element.content)
            )
            font = font_for(element.font_size, element.bold, font_path(element, fonts))
            lines = content.replace("\t", "    ").splitlines() or [""]
            inner_height = element.height - element.padding_top - element.padding_bottom
            if inner_height <= 0:
                raise ValueError(
                    Message(
                        "logicErrors.elementValue1TextPaddingLeavesNoSpaceForText",
                        value1=element.id,
                    )
                )
            # Rendering shrinks the entire block to fit its height. Measure at
            # that same scale so explicit line breaks do not leave unused width.
            scale = min(
                1.0, inner_height / text_block_height(font, len(lines), element.line_spacing)
            )
            # Round outward so floating point measurement never forces an extra wrap.
            element.width = (
                max(
                    0.1,
                    math.ceil(
                        max(text_width(font, line, element.character_spacing) for line in lines)
                        * scale
                        * 100
                    )
                    / 100,
                )
                + element.padding_left
                + element.padding_right
            )
            if element.width > 1000:
                raise ValueError(
                    Message("domainMessages.automaticallySizedTextExceedsTheMaximumElementWidth")
                )
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
            gap = holder.gap_mm if anchor.visible else 0
            if holder.axis == "horizontal":
                element.x += right + gap - left
            else:
                element.y += bottom + gap - top
            if not -1000 <= element.x <= 1000 or not -100 <= element.y <= 100:
                raise ValueError(
                    Message(
                        "domainMessages.distanceHolderPlacesAnElementBeyondSupportedCoordinates"
                    )
                )
            # Freeze the resolved geometry, not a relation that could move an old job later.
            element.distance_holder = None
        positioned.add(element.id)

    for element in resolved.elements:
        position(element)
    if resolved.auto_length:
        if spec.media_kind != "continuous":
            raise ValueError(Message("domainMessages.automaticLabelLengthRequiresContinuousMedia"))
        natural_length = fitted_length(resolved, spec.margin_mm)
        if natural_length < 10 and warnings is not None:
            warnings.append(
                "Automatic length would be below the 10 mm template minimum; "
                "the label is extended to 10 mm."
            )
        resolved.length_mm = max(10, math.ceil(natural_length * 100) / 100)
        if resolved.length_mm > 300:
            raise ValueError(Message("domainMessages.automaticLabelLengthExceedsThe300MmLimit"))
        resolved.auto_length = False
    return resolved


def fitted_length(document: TemplateDocument, margin_mm: float) -> float:
    return max(
        0,
        max((element_bounds(e)[2] for e in document.elements if e.visible), default=0) + margin_mm,
    )


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


def printable_vertical_bounds(width_mm: float, spec: RenderSpec) -> tuple[float, float]:
    band = (spec.printable_widths_mm or {}).get(f"{width_mm:g}")
    if band and spec.align_printable_band:
        height = round(width_mm * spec.dpi / 25.4)
        rows = min(height, round(band * spec.dpi / 25.4))
        top = (height - rows) // 2
        return top * width_mm / height, (top + rows) * width_mm / height
    margin = (width_mm - band) / 2 if band else spec.margin_mm
    return margin, width_mm - margin


def artwork_bounds(
    body: str,
    bounds: tuple[float, float, float, float],
    scale_x: float,
    scale_y: float,
    font_files: list[str],
) -> tuple[float, float, float, float] | None:
    """Measure ink on the canvas pixel grid, including artwork beyond the tape edges."""
    x, y, right, bottom = bounds
    left_px, top_px = math.floor(x * scale_x) - 1, math.floor(y * scale_y) - 1
    width = math.ceil(right * scale_x) - left_px + 1
    height = math.ceil(bottom * scale_y) - top_px + 1
    png = resvg_py.svg_to_bytes(
        svg_string=(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="{left_px / scale_x} {top_px / scale_y} '
            f'{width / scale_x} {height / scale_y}" preserveAspectRatio="none">'
            f'<rect x="{left_px / scale_x}" y="{top_px / scale_y}" '
            f'width="{width / scale_x}" height="{height / scale_y}" fill="white"/>'
            f"{body}</svg>"
        ),
        skip_system_fonts=True,
        font_files=font_files,
    )
    ink = (
        Image.open(io.BytesIO(png))
        .convert("L")
        .point([255 if value < 128 else 0 for value in range(256)])
    )
    box = ink.getbbox()
    if box is None:
        return None
    # Pixel centres determine whether any printed dots lie beyond a guide.
    return (
        (left_px + box[0] + 0.5) / scale_x,
        (top_px + box[1] + 0.5) / scale_y,
        (left_px + box[2] - 0.5) / scale_x,
        (top_px + box[3] - 0.5) / scale_y,
    )


@using_cache
def measure_logic_layout(
    document: TemplateDocument,
    data: Mapping[str, object],
    spec: RenderSpec,
    *,
    samples: bool = False,
    fonts: FontStore | None = None,
    allow_missing_assets: bool = False,
    warnings: list[str] | None = None,
) -> TemplateDocument:
    """Measure resolved text before evaluating geometry-dependent logic."""
    from app.templates.logic_engine import resolve_inputs
    from app.templates.logic_schema import ImageValue
    from app.templates.template_logic import display_value, logic_fields, sizing_source

    inputs = resolve_inputs(logic_fields(document), data, samples=samples)
    values = {
        name: display_value(value)
        for name, value in inputs.items()
        if not isinstance(value, ImageValue)
    }
    source = sizing_source(document, data, samples=samples)
    # Label length is fitted only after logic and is not a readable input while
    # automatic length is enabled. This pass measures object geometry only.
    source.auto_length = False
    for element in source.elements:
        if element.kind != "text" or not element.auto_width:
            continue
        if allow_missing_assets:
            try:
                font_path(element, fonts)
            except InvalidFontWeight:
                raise
            except ValueError:
                element.auto_width = False
    return resolve_layout(source, values, spec, fonts, warnings=warnings, measure_hidden=True)


@using_cache
def render_document(
    document: TemplateDocument,
    data: Mapping[str, object],
    spec: RenderSpec,
    samples: bool = False,
    fonts: FontStore | None = None,
    images: ImageStore | None = None,
    allow_missing_assets: bool = False,
) -> RenderOutput:
    if document.auto_length and spec.media_kind != "continuous":
        raise ValueError(Message("domainMessages.automaticLabelLengthRequiresContinuousMedia"))
    resolved_inputs = None
    layout_warnings: list[str] = []
    automatic_length = document.auto_length
    template_padding = 0.0
    if document.version == 2:
        from app.templates.template_logic import resolve_logic

        measured = measure_logic_layout(
            document,
            data,
            spec,
            samples=samples,
            fonts=fonts,
            allow_missing_assets=allow_missing_assets,
            warnings=layout_warnings,
        )
        document, evaluation = resolve_logic(document, data, samples=samples, measured=measured)
        # Text sizes include bound content and typography. Positioning logic
        # reads those measurements, then the physical label fits the result.
        document.auto_length = automatic_length
        resolved_inputs = evaluation.inputs
        values = {}
    else:
        values = resolve_values(document, data, samples)
    missing: dict[str, str] = {}
    if allow_missing_assets:
        document = document.model_copy(deep=True)
        for element in document.elements:
            if not element.visible:
                continue
            try:
                if element.kind == "text":
                    font_path(element, fonts)
                elif element.kind == "image" and element.image_asset:
                    if images is None:
                        raise ValueError(Message("domainMessages.imageLibraryUnavailable"))
                    images.path(element.image_asset)
            except InvalidFontWeight:
                raise
            except ValueError:
                missing[element.id] = "font" if element.kind == "text" else "image"
                # Resolve placement using the original box, without substituting font metrics.
                element.kind = "rectangle"
                element.auto_width = False
                element.font = "Noto Sans"
    from app.media import require_supported_media

    require_supported_media(
        document.media,
        document.width_mm,
        media_family=spec.media_family,
        media_kind=spec.media_kind,
        supported_widths_mm=spec.supported_widths_mm,
        fixed_label_sizes_mm=tuple((width, length) for width, length in spec.fixed_label_sizes_mm),
    )
    printable_top, printable_bottom = printable_vertical_bounds(document.width_mm, spec)
    document = resolve_layout(document, values, spec, fonts, warnings=layout_warnings)
    if (
        document.media.media_kind == "fixed_label"
        and document.length_mm != document.media.label_length_mm
    ):
        raise ValueError(
            Message("domainMessages.resolvedDesignLengthMustMatchTheFixedLabelStockLength")
        )
    if automatic_length:
        template_padding = max(0, 10 - fitted_length(document, spec.margin_mm))
    font_files = [str(FONT_DIR / "NotoSans.ttf"), str(FONT_DIR / "NotoSans-Bold.ttf")]
    font_files.extend(
        sorted(
            {
                path
                for e in document.elements
                if e.visible and e.kind == "text"
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
            f'<defs><clipPath id="printable"><rect x="{spec.margin_mm}" y="{printable_top}" '
            f'width="{document.length_mm - 2 * spec.margin_mm}" '
            f'height="{printable_bottom - printable_top}"/></clipPath></defs>'
            '<g clip-path="url(#printable)">'
        )
    for element in document.elements:
        if not element.visible:
            continue
        x, y, right, bottom = element_bounds(element)
        outside = (
            x < spec.margin_mm - 0.001
            or y < printable_top - 0.001
            or right > document.length_mm - spec.margin_mm + 0.001
            or bottom > printable_bottom + 0.001
        )
        if outside:
            if not clipping:
                raise ValueError(
                    Message(
                        "logicErrors.elementValue1IsOutsideThePrintableAreaValue2MmMargins",
                        value1=element.id,
                        value2=spec.margin_mm,
                    )
                )
        box = (x, y, right, bottom, element.id)
        boxes.append(box)
        content = (
            element.content
            if element.literal_content
            else TOKEN.sub(lambda match: values[match.group(1)], element.content)
        )
        if element.id in missing:
            body = missing_asset_svg(element, missing[element.id])
        elif element.kind == "text":
            body = text_svg(element, content, fonts)
        elif element.kind == "qr":
            qr_boxes.append(box)
            body = qr_svg(element, content, spec)
        elif element.kind == "barcode":
            qr_boxes.append(box)
            body = barcode_svg(element, content, spec, fonts)
        elif element.kind in ("datamatrix", "aztec"):
            qr_boxes.append(box)
            body = matrix_svg(element, content, spec)
        elif element.kind == "image":
            body = image_svg(element, images, spec.horizontal_dpi, spec.dpi)
        elif element.kind == "rectangle":
            inset = element.stroke / 2
            body = f'<rect x="{inset}" y="{inset}" width="{element.width - element.stroke}" height="{element.height - element.stroke}" stroke="black" stroke-width="{element.stroke}" fill="{"black" if element.filled else "none"}"/>'
        else:
            body = f'<path d="M0,{element.height / 2}h{element.width}" stroke="black" stroke-width="{element.stroke}"/>'
        artwork = f'<g transform="translate({element.x},{element.y}) rotate({element.rotation},{element.width / 2},{element.height / 2})">{body}</g>'
        if outside and clipping:
            # QR quiet zones are meaningful even where they contain no ink.
            visible = (
                (x, y, right, bottom)
                if element.kind in ("qr", "barcode", "datamatrix", "aztec")
                else artwork_bounds(
                    artwork,
                    (x, y, right, bottom),
                    px_width / document.length_mm,
                    px_height / document.width_mm,
                    font_files,
                )
            )
            if visible and (
                visible[0] < spec.margin_mm - 0.001
                or visible[1] < printable_top - 0.001
                or visible[2] > document.length_mm - spec.margin_mm + 0.001
                or visible[3] > printable_bottom + 0.001
            ):
                omitted = (
                    visible[2] < spec.margin_mm
                    or visible[3] < printable_top
                    or visible[0] > document.length_mm - spec.margin_mm
                    or visible[1] > printable_bottom
                )
                warnings.append(
                    f"Element {element.id} is {'omitted' if omitted else 'clipped'} at the printable area."
                )
        parts.append(artwork)
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
                code_name = {
                    "qr": "QR code",
                    "barcode": "Barcode",
                    "datamatrix": "Data Matrix",
                    "aztec": "Aztec code",
                }[next(e for e in document.elements if e.id == q[4]).kind]
                warnings.append(
                    f"{code_name} {q[4]} has overlapping element bounds. "
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
    image = source.point([255 if value >= 128 else 0 for value in range(256)], mode="1")
    return RenderOutput(
        svg,
        image,
        warnings,
        document,
        font_files,
        missing,
        template_padding,
        resolved_inputs,
        fonts,
    )


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
