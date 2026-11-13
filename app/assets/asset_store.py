"""Database-backed immutable assets; filesystem mode is reserved for legacy import."""

import hashlib
import json
import os
import re
import secrets
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import ScalarResult, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.asset_cache import cache_use, touch
from app.assets.binary_json import check_packet_size
from app.authn.identity import LOCAL_OWNER_ID
from app.i18n import Message
from app.models import StoredAsset

ASSET_ID = re.compile(r"^[a-f0-9]{64}$")


class AssetStore:
    suffix = "asset"

    def __init__(self, root: Path, factory: sessionmaker[Session] | None = None):
        self.root = root
        self.factory = factory
        self.unavailable: Callable[[str], bool] = lambda _: False

    def path(self, identifier: str, *, include_deleted: bool = False) -> Path:
        if not ASSET_ID.fullmatch(identifier):
            raise ValueError(Message("domainMessages.invalidAssetID"))
        if not include_deleted and self.unavailable(identifier):
            raise ValueError(
                Message("domainMessages.thisAssetWasDeletedRestoreOrReplaceItBeforePrinting")
            )
        path = self.root / f"{identifier}.{self.suffix}"
        if self.factory:
            with cache_use(), self.factory() as session:
                # Cached bytes never make a removed database record available.
                checksum = session.scalar(
                    select(StoredAsset.checksum).where(
                        StoredAsset.kind == self.suffix, StoredAsset.id == identifier
                    )
                )
                if checksum is None:
                    raise ValueError(Message("domainMessages.assetIsMissingFromTheDatabase"))
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                    asset = session.get(StoredAsset, (self.suffix, identifier))
                    assert asset is not None
                    if hashlib.sha256(asset.content).hexdigest() != checksum:
                        raise ValueError(
                            Message("domainMessages.assetFailedDatabaseIntegrityVerification")
                        )
                    self._write(path, asset.content)
                touch(path)
                return path
        if not path.is_file():
            raise ValueError(Message("domainMessages.assetIsMissingRestoreItFromYourDataBackup"))
        return path

    def metadata(self, identifier: str, *, include_deleted: bool = False) -> dict[str, Any]:
        if self.factory:
            if not ASSET_ID.fullmatch(identifier):
                raise ValueError(Message("domainMessages.invalidAssetID"))
            if not include_deleted and self.unavailable(identifier):
                raise ValueError(
                    Message("domainMessages.thisAssetWasDeletedRestoreOrReplaceItBeforePrinting")
                )
            with self.factory() as session:
                details = session.scalar(
                    select(StoredAsset.details).where(
                        StoredAsset.kind == self.suffix, StoredAsset.id == identifier
                    )
                )
                if details is None:
                    raise ValueError(Message("domainMessages.assetIsMissingFromTheDatabase"))
                return dict(details)
        self.path(identifier, include_deleted=include_deleted)
        metadata = dict(json.loads((self.root / f"{identifier}.json").read_text()))
        # Legacy assets gain ownership metadata without rewriting their immutable bytes.
        metadata.setdefault("owner_id", LOCAL_OWNER_ID)
        metadata.setdefault("scope", "personal")
        metadata.setdefault("group_id", None)
        return metadata

    def list(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        if self.factory:
            with self.factory() as session:
                entries: list[dict[str, Any]] = []
                rows: ScalarResult[dict[str, Any]] = session.scalars(
                    select(StoredAsset.details).where(StoredAsset.kind == self.suffix)
                )
                for details in rows:
                    if include_deleted or not self.unavailable(details["id"]):
                        entries.append(dict(details))
        else:
            entries = [
                self.metadata(path.stem, include_deleted=include_deleted)
                for path in self.root.glob("*.json")
                if include_deleted or not self.unavailable(path.stem)
            ]
        return sorted(
            entries,
            key=lambda item: (
                item.get("family", item.get("name", "")).lower(),
                item.get("style", "").lower(),
                item["id"],
            ),
        )

    def identifier(
        self, data: bytes, owner_id: str, scope: str = "personal", group_id: str | None = None
    ) -> str:
        namespace = owner_id if scope == "personal" else f"{owner_id}\0{scope}\0{group_id or ''}"
        identifier = hashlib.sha256(namespace.encode() + b"\0" + data).hexdigest()
        moved = False
        if self.exists(identifier) and not self.unavailable(identifier):
            metadata = self.metadata(identifier)
            moved = (metadata["scope"], metadata["group_id"]) != (scope, group_id)
        if self.unavailable(identifier) or moved:
            # Re-uploading never resurrects deleted references or overwrites held bytes.
            identifier = hashlib.sha256(secrets.token_bytes(32) + data).hexdigest()
        return identifier

    def set_sharing(
        self, identifier: str, scope: str, group_id: str | None, *, session: Session | None = None
    ) -> dict[str, Any]:
        metadata = self.metadata(identifier)
        metadata.update(scope=scope, group_id=group_id)
        self.save_metadata(identifier, metadata, session=session)
        return metadata

    def purge(self, identifier: str, *, session: Session | None = None) -> None:
        if not ASSET_ID.fullmatch(identifier):
            raise ValueError(Message("domainMessages.invalidAssetID"))
        if self.factory:
            if session is None:
                with self.factory.begin() as transaction:
                    self.purge(identifier, session=transaction)
                return
            session.execute(
                delete(StoredAsset).where(
                    StoredAsset.kind == self.suffix, StoredAsset.id == identifier
                )
            )
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

    def set_archived(
        self, identifier: str, archived: bool, *, session: Session | None = None
    ) -> dict[str, Any]:
        metadata = self.metadata(identifier)
        metadata["archived"] = archived
        self.save_metadata(identifier, metadata, session=session)
        return metadata

    def exists(self, identifier: str) -> bool:
        if self.factory:
            with self.factory() as session:
                return (
                    session.scalar(
                        select(StoredAsset.id).where(
                            StoredAsset.kind == self.suffix, StoredAsset.id == identifier
                        )
                    )
                    is not None
                )
        return (self.root / f"{identifier}.json").exists()

    def save_metadata(
        self, identifier: str, metadata: dict[str, Any], *, session: Session | None = None
    ) -> None:
        if self.factory:
            if session is None:
                with self.factory.begin() as transaction:
                    self.save_metadata(identifier, metadata, session=transaction)
                return
            asset = session.get(StoredAsset, (self.suffix, identifier))
            if asset is None:
                raise ValueError(Message("domainMessages.assetIsMissingFromTheDatabase"))
            asset.details = metadata
        else:
            self._write(self.root / f"{identifier}.json", json.dumps(metadata).encode())

    def save(
        self,
        identifier: str,
        metadata: dict[str, Any],
        content: bytes,
        source: bytes | None = None,
        *,
        session: Session | None = None,
    ) -> None:
        if self.factory:
            if session is None:
                with self.factory.begin() as transaction:
                    self.save(identifier, metadata, content, source, session=transaction)
                return
            check_asset_capacity(session, content, source, metadata)
            session.add(
                StoredAsset(
                    kind=self.suffix,
                    id=identifier,
                    details=metadata,
                    content=content,
                    source=source,
                    checksum=hashlib.sha256(content).hexdigest(),
                )
            )
            session.flush()
        else:
            self._write(self.root / f"{identifier}.{self.suffix}", content)
            if source is not None:
                self._write(self.root / f"{identifier}.source", source)
            self._write(self.root / f"{identifier}.json", json.dumps(metadata).encode())


def check_asset_capacity(
    session: Session, content: bytes, source: bytes | None, details: dict[str, Any]
) -> None:
    connection = session.connection()
    if connection.dialect.name == "mariadb":
        limit = int(connection.exec_driver_sql("SELECT @@max_allowed_packet").scalar_one())
        check_packet_size([content, source, json.dumps(details)], limit)
