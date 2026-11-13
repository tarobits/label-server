"""Small, sanitized profile pictures stored with the account database."""

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.i18n import Message
from app.models import StoredAsset

MAX_UPLOAD = 5_000_000


def avatar_path(root: Path, user_id: str) -> Path:
    return root / "avatars" / (hashlib.sha256(user_id.encode()).hexdigest() + ".png")


def avatar_version(session: Session, user_id: str) -> str | None:
    return session.scalar(
        select(StoredAsset.checksum).where(
            StoredAsset.kind == "avatar",
            StoredAsset.id == hashlib.sha256(user_id.encode()).hexdigest(),
        )
    )


def read_avatar(session: Session, user_id: str) -> bytes:
    asset = session.get(StoredAsset, ("avatar", hashlib.sha256(user_id.encode()).hexdigest()))
    if asset is None:
        raise FileNotFoundError("No profile picture")
    return asset.content


def remove_avatar(session: Session, user_id: str) -> None:
    asset = session.get(StoredAsset, ("avatar", hashlib.sha256(user_id.encode()).hexdigest()))
    if asset is not None:
        session.delete(asset)


def normalize_avatar(data: bytes) -> bytes:
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError(Message("authValidation.chooseAPNGJPEGOrWebPImageOfAtMost5MB"))
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP") or getattr(source, "n_frames", 1) != 1:
                raise ValueError(Message("authValidation.chooseAStillPNGJPEGOrWebPImage"))
            if source.width * source.height > 16_000_000 or max(source.size) > 8192:
                raise ValueError(
                    Message(
                        "authValidation.profilePicturesAreLimitedTo16MegapixelsAnd8192PixelsPerSide"
                    )
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
        raise ValueError(Message("authValidation.imageCouldNotBeDecoded")) from error


def save_avatar(session: Session, user_id: str, normalized: bytes) -> None:
    identifier = hashlib.sha256(user_id.encode()).hexdigest()
    asset = session.get(StoredAsset, ("avatar", identifier))
    if asset is None:
        asset = StoredAsset(kind="avatar", id=identifier, details={"user_id": user_id}, source=None)
        session.add(asset)
    asset.content = normalized
    asset.checksum = hashlib.sha256(normalized).hexdigest()
    session.flush()
