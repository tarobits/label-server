"""Atomic files and immutable asset references shared by asset libraries."""

import hashlib
import json
import os
import re
import secrets
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.identity import LOCAL_OWNER_ID

ASSET_ID = re.compile(r"^[a-f0-9]{64}$")


class AssetStore:
    suffix = "asset"

    def __init__(self, root: Path):
        self.root = root
        self.unavailable: Callable[[str], bool] = lambda _: False

    def path(self, identifier: str, *, include_deleted: bool = False) -> Path:
        if not ASSET_ID.fullmatch(identifier):
            raise ValueError("Invalid asset ID")
        if not include_deleted and self.unavailable(identifier):
            raise ValueError("This asset was deleted; restore or replace it before printing")
        path = self.root / f"{identifier}.{self.suffix}"
        if not path.is_file():
            raise ValueError("Asset is missing; restore it from your data backup")
        return path

    def metadata(self, identifier: str, *, include_deleted: bool = False) -> dict[str, Any]:
        self.path(identifier, include_deleted=include_deleted)
        metadata = dict(json.loads((self.root / f"{identifier}.json").read_text()))
        # Legacy assets gain ownership metadata without rewriting their immutable bytes.
        metadata.setdefault("owner_id", LOCAL_OWNER_ID)
        return metadata

    def list(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        return sorted(
            [
                self.metadata(path.stem, include_deleted=include_deleted)
                for path in self.root.glob("*.json")
                if include_deleted or not self.unavailable(path.stem)
            ],
            key=lambda item: (
                item.get("family", item.get("name", "")).lower(),
                item.get("style", "").lower(),
                item["id"],
            ),
        )

    def identifier(self, data: bytes, owner_id: str) -> str:
        identifier = hashlib.sha256(owner_id.encode() + b"\0" + data).hexdigest()
        if self.unavailable(identifier):
            # Re-uploading never resurrects deleted references or overwrites held bytes.
            identifier = hashlib.sha256(secrets.token_bytes(32) + data).hexdigest()
        return identifier

    def purge(self, identifier: str) -> None:
        if not ASSET_ID.fullmatch(identifier):
            raise ValueError("Invalid asset ID")
        for path in self.root.glob(f"{identifier}.*"):
            path.unlink(missing_ok=True)

    def _write(self, path: Path, data: bytes) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def set_archived(self, identifier: str, archived: bool) -> dict[str, Any]:
        metadata = self.metadata(identifier)
        metadata["archived"] = archived
        self._write(self.root / f"{identifier}.json", json.dumps(metadata).encode())
        return metadata
