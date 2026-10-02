"""Atomic files and immutable asset references shared by asset libraries."""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.identity import LOCAL_OWNER_ID

ASSET_ID = re.compile(r"^[a-f0-9]{64}$")


class AssetStore:
    suffix = "asset"

    def __init__(self, root: Path):
        self.root = root

    def path(self, identifier: str) -> Path:
        if not ASSET_ID.fullmatch(identifier):
            raise ValueError("Invalid asset ID")
        path = self.root / f"{identifier}.{self.suffix}"
        if not path.is_file():
            raise ValueError("Asset is missing; restore it from your data backup")
        return path

    def metadata(self, identifier: str) -> dict[str, Any]:
        self.path(identifier)
        metadata = dict(json.loads((self.root / f"{identifier}.json").read_text()))
        # Legacy assets gain ownership metadata without rewriting their immutable bytes.
        metadata.setdefault("owner_id", LOCAL_OWNER_ID)
        return metadata

    def list(self) -> list[dict[str, Any]]:
        return sorted(
            [self.metadata(path.stem) for path in self.root.glob("*.json")],
            key=lambda item: (
                item.get("family", item.get("name", "")).lower(),
                item.get("style", "").lower(),
                item["id"],
            ),
        )

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
