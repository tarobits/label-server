"""Small, sanitized profile pictures kept with the backed-up local assets."""

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.asset_store import AssetStore

MAX_UPLOAD = 5_000_000


def avatar_path(root: Path, user_id: str) -> Path:
    return root / "avatars" / (hashlib.sha256(user_id.encode()).hexdigest() + ".png")


def avatar_version(root: Path, user_id: str) -> str | None:
    try:
        return str(avatar_path(root, user_id).stat().st_mtime_ns)
    except FileNotFoundError:
        return None


def normalize_avatar(data: bytes) -> bytes:
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("Choose a PNG, JPEG or WebP image of at most 5 MB")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP") or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Choose a still PNG, JPEG or WebP image")
            if source.width * source.height > 16_000_000 or max(source.size) > 8192:
                raise ValueError(
                    "Profile pictures are limited to 16 megapixels and 8192 pixels per side"
                )
            source.load()
            picture = ImageOps.fit(
                ImageOps.exif_transpose(source).convert("RGBA"),
                (256, 256),
                Image.Resampling.LANCZOS,
            )
            # Rebuild pixels to discard EXIF, comments and other uploaded metadata.
            clean = Image.frombytes("RGBA", picture.size, picture.tobytes())
            output = io.BytesIO()
            clean.save(output, format="PNG")
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("Image could not be decoded") from error


def save_avatar(root: Path, user_id: str, normalized: bytes) -> None:
    path = avatar_path(root, user_id)
    AssetStore(path.parent)._write(path, normalized)
