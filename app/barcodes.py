"""Bounded linear barcode encoding; physical layout stays in the renderer."""

import re
from functools import lru_cache

import zxingcpp
from barcode.codex import Code39, Code128  # type: ignore[import-untyped]
from barcode.ean import (  # type: ignore[import-untyped]
    EuropeanArticleNumber8,
    EuropeanArticleNumber13,
)


@lru_cache(maxsize=128)
def encode_matrix(kind: str, content: str) -> tuple[tuple[bool, ...], ...]:
    if not content or len(content.encode("utf-8")) > 1000:
        raise ValueError("Matrix code content must contain between 1 and 1000 UTF-8 bytes")
    format = {
        "datamatrix": zxingcpp.BarcodeFormat.DataMatrix,
        "aztec": zxingcpp.BarcodeFormat.Aztec,
    }[kind]
    try:
        code = zxingcpp.create_barcode(content, format)
        image = memoryview(
            zxingcpp.write_barcode_to_image(code, scale=1, add_hrt=False, add_quiet_zones=True)
        )
    except (ValueError, RuntimeError) as error:
        raise ValueError("Content cannot be encoded in this matrix code") from error
    if image.shape is None or len(image.shape) != 2:
        raise ValueError("Barcode encoder returned an invalid matrix")
    height, width = image.shape
    return tuple(tuple(image[row, column] == 0 for column in range(width)) for row in range(height))


@lru_cache(maxsize=256)
def encode_barcode(kind: str, content: str) -> tuple[str, str]:
    if not content or len(content) > 200:
        raise ValueError("Barcode content must contain between 1 and 200 characters")
    if kind in ("ean13", "ean8"):
        size = 13 if kind == "ean13" else 8
        if not re.fullmatch(r"[0-9]+", content) or len(content) not in (size - 1, size):
            raise ValueError(
                f"EAN-{size} requires {size - 1} digits, or {size} including its check digit"
            )
        code = (EuropeanArticleNumber13 if size == 13 else EuropeanArticleNumber8)(
            content[: size - 1]
        )
        full = code.get_fullcode()
        if len(content) == size and content != full:
            raise ValueError(f"EAN-{size} check digit is incorrect")
    elif kind == "code39":
        if not re.fullmatch(r"[A-Z0-9 .$/+%-]+", content):
            raise ValueError("Code 39 supports uppercase letters, digits, spaces and - . $ / + %")
        code = Code39(content, add_checksum=False)
    elif kind == "code128":
        if not re.fullmatch(r"[\x20-\x7e]+", content):
            raise ValueError("Code 128 supports printable ASCII characters")
        code = Code128(content)
    else:
        raise ValueError("Unsupported barcode format")
    return code.build()[0], code.get_fullcode()
