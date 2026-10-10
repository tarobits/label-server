"""Immutable, content-addressed font files alongside the application's data."""

import hashlib
import io
import json
from typing import Any

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from PIL import ImageFont

from app.asset_store import AssetStore
from app.identity import LOCAL_OWNER_ID

MAX_FONT_BYTES = 5_000_000


class FontStore(AssetStore):
    suffix = "font"

    def add(self, data: bytes, *, owner_id: str = LOCAL_OWNER_ID) -> dict[str, Any]:
        if not data or len(data) > MAX_FONT_BYTES:
            raise ValueError("Upload a font of at most 5 MB")
        if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO"):
            raise ValueError("Upload a static TTF or OTF font (not a collection or web font)")
        identifier = hashlib.sha256(owner_id.encode() + b"\0" + data).hexdigest()
        if (self.root / f"{identifier}.json").exists():
            return self.metadata(identifier)
        alias = f"LabelFont_{identifier[:48]}"
        try:
            with TTFont(io.BytesIO(data), lazy=False, recalcTimestamp=False) as font:
                if "fvar" in font:
                    raise ValueError(
                        "Variable fonts are not supported yet; upload a static font face"
                    )
                if not {"name", "cmap", "head", "hhea", "hmtx", "maxp"}.issubset(font.keys()):
                    raise ValueError("Font is missing required metrics or character tables")
                if not 1 <= font["maxp"].numGlyphs <= 20000:
                    raise ValueError("Font must contain between 1 and 20000 glyphs")
                if not font.getBestCmap():
                    raise ValueError("Font must have a Unicode character map")
                if not (("glyf" in font) or ("CFF " in font)):
                    raise ValueError("Font must contain scalable outlines")
                if any(table in font for table in ("SVG ", "CBDT", "sbix", "COLR")):
                    raise ValueError("Color/bitmap fonts are not supported")
                names = font["name"]
                family = (names.getBestFamilyName() or "Uploaded font")[:120]
                style = (names.getBestSubFamilyName() or "Regular")[:120]
                if style.lower() == "regular" and "OS/2" in font:
                    weight = font["OS/2"].usWeightClass
                    italic = bool(font["OS/2"].fsSelection & 1)
                    style = "Bold" if weight >= 700 else "Regular"
                    if italic:
                        style = "Italic" if style == "Regular" else f"{style} Italic"
                # Give each immutable asset a unique rendering family, including
                # when two uploads have identical original family/style names.
                for name in names.names:
                    if name.nameID in (1, 4, 6, 16):
                        name.string = alias.encode(name.getEncoding())
                    elif name.nameID in (2, 17):
                        name.string = "Regular".encode(name.getEncoding())
                # Some valid fonts omit full/PostScript or Windows names.
                # Supply complete Unicode records so the rasterizer can select them.
                for name_id in (1, 4, 6, 16):
                    names.setName(alias, name_id, 3, 1, 0x409)
                for name_id in (2, 17):
                    names.setName("Regular", name_id, 3, 1, 0x409)
                if "CFF " in font:
                    cff = font["CFF "].cff
                    cff.fontNames = [alias]
                    for top in cff.topDictIndex:
                        top.FamilyName = top.FullName = alias
                output = io.BytesIO()
                font.save(output)
                normalized = output.getvalue()
                if len(normalized) > MAX_FONT_BYTES:
                    raise ValueError("Normalized font exceeds 5 MB")
                ImageFont.truetype(io.BytesIO(normalized), 100).getmetrics()
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("Font could not be read; upload a valid static TTF or OTF") from error
        metadata = {
            "id": identifier,
            "owner_id": owner_id,
            "family": family,
            "style": style,
            "render_family": alias,
            "size_bytes": len(data),
            "archived": False,
        }
        self._write(self.root / f"{identifier}.font", normalized)
        self._write(self.root / f"{identifier}.json", json.dumps(metadata).encode())
        return metadata
