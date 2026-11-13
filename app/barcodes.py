"""Bounded linear barcode encoding; physical layout stays in the renderer."""

import re
from functools import lru_cache

import zxingcpp
from barcode.codex import Code39, Code128  # type: ignore[import-untyped]
from barcode.ean import (  # type: ignore[import-untyped]
    EuropeanArticleNumber8,
    EuropeanArticleNumber13,
)

from app.i18n import Message


@lru_cache(maxsize=128)
def encode_matrix(kind: str, content: str) -> tuple[tuple[bool, ...], ...]:
    if not content or len(content.encode("utf-8")) > 1000:
        raise ValueError(
            Message("domainMessages.matrixCodeContentMustContainBetween1And1000UTF8Bytes")
        )
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
        raise ValueError(
            Message("domainMessages.contentCannotBeEncodedInThisMatrixCode")
        ) from error
    if image.shape is None or len(image.shape) != 2:
        raise ValueError(Message("domainMessages.barcodeEncoderReturnedAnInvalidMatrix"))
    height, width = image.shape
    return tuple(tuple(image[row, column] == 0 for column in range(width)) for row in range(height))


@lru_cache(maxsize=256)
def encode_barcode(kind: str, content: str) -> tuple[str, str]:
    if not content or len(content) > 200:
        raise ValueError(
            Message("domainMessages.barcodeContentMustContainBetween1And200Characters")
        )
    if kind in ("ean13", "ean8"):
        size = 13 if kind == "ean13" else 8
        if not re.fullmatch(r"[0-9]+", content) or len(content) not in (size - 1, size):
            raise ValueError(
                Message(
                    "logicErrors.eanValue1RequiresValue2DigitsOrValue3IncludingItsCheckDigit",
                    value1=size,
                    value2=size - 1,
                    value3=size,
                )
            )
        code = (EuropeanArticleNumber13 if size == 13 else EuropeanArticleNumber8)(
            content[: size - 1]
        )
        full = code.get_fullcode()
        if len(content) == size and content != full:
            raise ValueError(Message("logicErrors.eanValue1CheckDigitIsIncorrect", value1=size))
    elif kind == "code39":
        if not re.fullmatch(r"[A-Z0-9 .$/+%-]+", content):
            raise ValueError(
                Message("domainMessages.code39SupportsUppercaseLettersDigitsSpacesAnd")
            )
        code = Code39(content, add_checksum=False)
    elif kind == "code128":
        if not re.fullmatch(r"[\x20-\x7e]+", content):
            raise ValueError(Message("domainMessages.code128SupportsPrintableASCIICharacters"))
        code = Code128(content)
    else:
        raise ValueError(Message("domainMessages.unsupportedBarcodeFormat"))
    return code.build()[0], code.get_fullcode()
