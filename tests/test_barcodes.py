import pytest
import zxingcpp
from PIL import Image

from app.barcodes import encode_barcode
from app.logic_source import compile_source
from app.render import RenderSpec, render_document
from app.template_logic import logic_fields, logic_targets
from app.template_schema import TemplateDocument


@pytest.mark.parametrize(
    "kind,format,content,expected",
    [
        ("barcode", "code128", "Inventory-42", "Inventory-42"),
        ("barcode", "code39", "ABC-42", "ABC-42"),
        ("barcode", "ean13", "590123412345", "5901234123457"),
        ("barcode", "ean8", "9638507", "96385074"),
        ("datamatrix", "code128", "Data Matrix 42", "Data Matrix 42"),
        ("aztec", "code128", "Aztec 42", "Aztec 42"),
    ],
)
@pytest.mark.parametrize("rotation,dpi", [(0, 180), (90, 180), (0, 360), (90, 360)])
def test_codes_decode_at_device_resolution(kind, format, content, expected, rotation, dpi):
    doc = TemplateDocument.model_validate(
        {
            "width_mm": 80,
            "length_mm": 100,
            "elements": [
                {
                    "id": "code",
                    "kind": kind,
                    "barcode_format": format,
                    "barcode_caption": True,
                    "content": content,
                    "x": 25,
                    "y": 30,
                    "width": 70 if kind == "barcode" else 24,
                    "height": 15 if kind == "barcode" else 24,
                    "rotation": rotation,
                }
            ],
        }
    )
    image = render_document(doc, {}, RenderSpec(dpi_x=dpi)).image
    if dpi == 360:
        image = image.resize((image.width, image.height * 2), Image.Resampling.NEAREST)
    result = zxingcpp.read_barcode(image)
    assert result is not None
    assert result.text == expected


@pytest.mark.parametrize(
    "kind,content",
    [
        ("ean13", "5901234123450"),
        ("ean8", "96385070"),
        ("code39", "lowercase"),
        ("code128", "😀"),
        ("ean13", "123"),
        ("code128", ""),
    ],
)
def test_invalid_content_is_not_silently_changed(kind, content):
    with pytest.raises(ValueError):
        encode_barcode(kind, content)


@pytest.mark.parametrize("kind", ["barcode", "datamatrix", "aztec"])
def test_code_content_can_be_bound_by_logic_and_small_codes_are_rejected(kind):
    raw = {
        "version": 2,
        "width_mm": 24,
        "length_mm": 100,
        "fields": [{"name": "payload", "label": "Payload", "type": "text", "default": "12345678"}],
        "elements": [
            {
                "id": "code",
                "logic_name": "code1",
                "kind": kind,
                "x": 2,
                "y": 2,
                "width": 70 if kind == "barcode" else 20,
                "height": 20,
                "barcode_caption": False,
            }
        ],
    }
    doc = TemplateDocument.model_validate(raw)
    raw["logic"] = compile_source(
        "code1.content = payload;", logic_fields(doc), logic_targets(doc)
    ).model_dump()
    doc = TemplateDocument.model_validate(raw)
    rendered = render_document(doc, {"payload": "87654321"}, RenderSpec())
    assert rendered.document.elements[0].content == "87654321"
    result = zxingcpp.read_barcode(rendered.image)
    assert result is not None and result.text == "87654321"
    doc.elements[0].width = 2
    with pytest.raises(ValueError, match="too (narrow|small)"):
        render_document(doc, {}, RenderSpec())
