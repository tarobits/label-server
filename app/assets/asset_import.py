"""One-time, verified import. Retained legacy files never become a fallback store."""

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.asset_store import ASSET_ID, AssetStore, check_asset_capacity
from app.models import AssetImport, StoredAsset, User


def import_assets(session: Session, root: Path) -> None:
    if session.get(AssetImport, "legacy-files-v1"):
        return
    for kind, directory in (("image", "images"), ("font", "fonts")):
        legacy = AssetStore(root / directory)
        legacy.suffix = kind
        for path in sorted(legacy.root.glob("*.json")):
            if not ASSET_ID.fullmatch(path.stem):
                raise ValueError("Legacy asset has an invalid identifier")
            details = legacy.metadata(path.stem, include_deleted=True)
            if details.get("id") != path.stem:
                raise ValueError("Legacy asset metadata does not match its identifier")
            content = legacy.path(path.stem, include_deleted=True).read_bytes()
            source_path = legacy.root / f"{path.stem}.source"
            source = source_path.read_bytes() if source_path.exists() else None
            save_import(session, kind, path.stem, details, content, source)
        # Missing metadata is also an error; importing a partial library must not succeed.
        for path in legacy.root.glob(f"*.{kind}"):
            if not path.with_suffix(".json").is_file():
                raise ValueError("Legacy asset is missing its ownership metadata")
    for user in session.scalars(select(User)):
        identifier = hashlib.sha256(user.id.encode()).hexdigest()
        path = root / "avatars" / f"{identifier}.png"
        if path.exists():
            content = path.read_bytes()
            save_import(session, "avatar", identifier, {"user_id": user.id}, content, None)
    session.add(AssetImport(id="legacy-files-v1"))
    session.flush()


def save_import(
    session: Session,
    kind: str,
    identifier: str,
    details: dict[str, Any],
    content: bytes,
    source: bytes | None,
) -> None:
    existing = session.get(StoredAsset, (kind, identifier))
    checksum = hashlib.sha256(content).hexdigest()
    if existing is None:
        check_asset_capacity(session, content, source, details)
        existing = StoredAsset(
            kind=kind,
            id=identifier,
            details=details,
            content=content,
            source=source,
            checksum=checksum,
        )
        session.add(existing)
        session.flush()
        session.expire(existing)
    if (
        existing.content != content
        or existing.source != source
        or existing.details != details
        or existing.checksum != checksum
    ):
        raise ValueError("Asset import verification failed; original files were retained")


def archive_legacy_assets(factory: sessionmaker[Session], root: Path) -> Path | None:
    """Archive only after the import transaction commits; rename is atomic.

    If a process stops between commit and rename, the next startup retries the
    archive without importing stale metadata. A failed move leaves the source intact.
    """
    with factory() as session:
        if session.get(AssetImport, "legacy-files-v1") is None:
            raise ValueError("Asset import must commit before archiving its source files")
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Legacy assets must be a regular directory before archiving")
    backups = root.parent / "backups"
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backups / f"assets-{stamp}-{uuid.uuid4().hex[:12]}"
    root.rename(destination)
    return destination
