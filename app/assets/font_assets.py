"""Immutable uploaded fonts normalized for rendering and stored in the database."""

import io
from typing import Any

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from PIL import ImageFont
from sqlalchemy.orm import Session

from app.assets.asset_store import AssetStore
from app.assets.font_variations import rename_face, weight_info
from app.authn.identity import LOCAL_OWNER_ID
from app.i18n import Message

MAX_FONT_BYTES = 5_000_000


class FontStore(AssetStore):
    suffix = "font"

    def add(
        self,
        data: bytes,
        *,
        owner_id: str = LOCAL_OWNER_ID,
        scope: str = "personal",
        group_id: str | None = None,
        session: Session | None = None,
    ) -> dict[str, Any]:
        if not data or len(data) > MAX_FONT_BYTES:
            raise ValueError(Message("domainMessages.uploadAFontOfAtMost5MB"))
        if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO"):
            raise ValueError(Message("domainMessages.uploadATTFOrOTFFontNotACollectionOrWebFont"))
        identifier = self.identifier(data, owner_id, scope, group_id)
        if self.exists(identifier):
            return self.metadata(identifier)
        alias = f"LabelFont_{identifier[:48]}"
        try:
            with TTFont(io.BytesIO(data), lazy=False, recalcTimestamp=False) as font:
                weights = weight_info(font)
                if not {"name", "cmap", "head", "hhea", "hmtx", "maxp"}.issubset(font.keys()):
                    raise ValueError(
                        Message("domainMessages.fontIsMissingRequiredMetricsOrCharacterTables")
                    )
                if not 1 <= font["maxp"].numGlyphs <= 20000:
                    raise ValueError(
                        Message("domainMessages.fontMustContainBetween1And20000Glyphs")
                    )
                if not font.getBestCmap():
                    raise ValueError(Message("domainMessages.fontMustHaveAUnicodeCharacterMap"))
                if not any(table in font for table in ("glyf", "CFF ", "CFF2")):
                    raise ValueError(Message("domainMessages.fontMustContainScalableOutlines"))
                if any(table in font for table in ("SVG ", "CBDT", "sbix", "COLR")):
                    raise ValueError(Message("domainMessages.colorBitmapFontsAreNotSupported"))
                names = font["name"]
                family = (names.getBestFamilyName() or "Uploaded font")[:120]
                style = (names.getBestSubFamilyName() or "Regular")[:120]
                if style.lower() == "regular" and "OS/2" in font:
                    # fontTools populates these table fields dynamically when decoding.
                    weight = int(getattr(font["OS/2"], "usWeightClass"))
                    italic = bool(int(getattr(font["OS/2"], "fsSelection")) & 1)
                    style = "Bold" if weight >= 700 else "Regular"
                    if italic:
                        style = "Italic" if style == "Regular" else f"{style} Italic"
                # Give each immutable asset a unique rendering family, including
                # when two uploads have identical original family/style names.
                rename_face(font, alias)
                output = io.BytesIO()
                font.save(output)
                normalized = output.getvalue()
                if len(normalized) > MAX_FONT_BYTES:
                    raise ValueError(Message("domainMessages.normalizedFontExceeds5MB"))
                ImageFont.truetype(io.BytesIO(normalized), 100).getmetrics()
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(
                Message("domainMessages.fontCouldNotBeReadUploadAValidTTFOrOTF")
            ) from error
        metadata = {
            "id": identifier,
            "owner_id": owner_id,
            "scope": scope,
            "group_id": group_id,
            "family": family,
            "style": style,
            "render_family": alias,
            "size_bytes": len(data),
            "archived": False,
            **weights,
        }
        self.save(identifier, metadata, normalized, session=session)
        return metadata

    def list(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        entries = super().list(include_deleted=include_deleted)
        for entry in entries:
            if "weight" not in entry:
                with TTFont(self.path(entry["id"], include_deleted=include_deleted)) as font:
                    entry.update(weight_info(font))
        return entries
