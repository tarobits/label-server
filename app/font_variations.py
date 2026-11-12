"""Validated font weights and immutable static instances shared by both renderers."""

import hashlib
import io
import math
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from fontTools.varLib.instancer import instantiateVariableFont  # type: ignore[import-untyped]

from app.asset_cache import touch, using_cache
from app.asset_store import AssetStore

_lock = RLock()


class InvalidFontWeight(ValueError):
    """Invalid typography must not be mistaken for a missing asset."""


def weight_info(font: Any) -> dict[str, Any]:
    weight = int(getattr(font.get("OS/2"), "usWeightClass", 400))
    axes = font["fvar"].axes if "fvar" in font else []
    if len(axes) > 16 or len({axis.axisTag for axis in axes}) != len(axes):
        raise ValueError("Font has invalid variation axes")
    weight_axis = None
    for axis in axes:
        values = (axis.minValue, axis.defaultValue, axis.maxValue)
        if (
            not all(math.isfinite(value) for value in values)
            or not values[0] <= values[1] <= values[2]
        ):
            raise ValueError("Font has invalid variation limits")
        if axis.axisTag == "wght":
            if not 1 <= axis.minValue <= axis.maxValue <= 1000:
                raise ValueError("Font weight range must be between 1 and 1000")
            weight_axis = {
                "min": axis.minValue,
                "max": axis.maxValue,
                "default": axis.defaultValue,
            }
            weight = axis.defaultValue
    return {"weight": weight, "weight_axis": weight_axis, "variable": bool(axes)}


def rename_face(font: Any, alias: str) -> None:
    names = font["name"]
    for name in names.names:
        if name.nameID in (1, 4, 6, 16):
            name.string = alias.encode(name.getEncoding())
        elif name.nameID in (2, 17):
            name.string = "Regular".encode(name.getEncoding())
    for name_id in (1, 4, 6, 16):
        names.setName(alias, name_id, 3, 1, 0x409)
    for name_id in (2, 17):
        names.setName("Regular", name_id, 3, 1, 0x409)
    if "CFF " in font:
        cff = font["CFF "].cff
        cff.fontNames = [alias]
        for top in cff.topDictIndex:
            top.FamilyName = top.FullName = alias


@using_cache
def static_instance(source: Path, weight: float | None, root: Path | None = None) -> Path:
    data = source.read_bytes()
    digest = hashlib.sha256(data + f"/weight-v1/{weight}".encode()).hexdigest()
    folder = root or Path(tempfile.gettempdir()) / "label-font-instances"
    # PostScript font names must fit in 63 characters, including our prefix.
    target = folder / f"LabelWeight_{digest[:48]}.ttf"
    with _lock:
        if target.is_file():
            touch(target)
            return target
        with TTFont(io.BytesIO(data), recalcTimestamp=False) as font:
            info = weight_info(font)
            axis = info["weight_axis"]
            if weight is not None:
                if axis:
                    if not axis["min"] <= weight <= axis["max"]:
                        raise InvalidFontWeight(
                            f"Font weight must be between {axis['min']:g} and {axis['max']:g}"
                        )
                elif weight != info["weight"]:
                    raise InvalidFontWeight("This static font only supports its original weight")
            if "fvar" in font:
                coordinates = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
                if axis and weight is not None:
                    coordinates["wght"] = weight
                cff2 = "CFF2" in font
                font = instantiateVariableFont(
                    font, coordinates, inplace=True, static=True, downgradeCFF2=cff2
                )
                if cff2:
                    # CFF downgrade assigns CID glyph names. Round-trip by glyph
                    # index before recalculating metrics so cmap, hmtx and CFF
                    # use the same names again (including fonts with post v2).
                    font.recalcBBoxes = False
                    converted = io.BytesIO()
                    font.save(converted)
                    font.close()
                    font = TTFont(io.BytesIO(converted.getvalue()), recalcTimestamp=False)
            rename_face(font, target.stem)
            output = io.BytesIO()
            font.save(output)
            if output.tell() > 5_000_000:
                raise ValueError("Generated font instance exceeds 5 MB")
        AssetStore(folder)._write(target, output.getvalue())
    return target
