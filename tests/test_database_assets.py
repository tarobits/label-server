"""Durable assets, verified legacy import and disposable rendering cache."""

import hashlib
import json
import os
import shutil
import time

import pytest
from sqlalchemy import delete, select
from test_access_security import accounts as accounts
from test_avatars import picture

from app.asset_cache import cache_use, expire
from app.asset_import import import_assets
from app.avatars import avatar_path, avatar_version, normalize_avatar, read_avatar
from app.binary_json import decode_binary
from app.font_assets import FontStore
from app.image_assets import ImageStore
from app.models import AssetImport, StoredAsset
from app.render import FONT_DIR
from scripts.database_maintenance import encode
from scripts.migrate_database import digest

SVG = b'<svg viewBox="0 0 20 10"><rect width="20" height="10" fill="black"/></svg>'


def upload(client, data=SVG):
    response = client.post("/api/image-assets?name=Durable", content=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_database_is_authoritative_after_cache_loss_and_corruption(client):
    identifier = upload(client)
    store = client.app.state.images
    path = store.path(identifier)
    original = path.read_bytes()
    with client.app.state.factory() as session:
        asset = session.get(StoredAsset, ("image", identifier))
        assert asset.content == original and asset.source == SVG
        assert asset.checksum == hashlib.sha256(original).hexdigest()
    assert not (store.root / f"{identifier}.json").exists()
    path.write_bytes(b"corrupt cache")
    assert store.path(identifier).read_bytes() == original
    preview = client.get(f"/api/image-assets/{identifier}/preview").content
    shutil.rmtree(store.root.parent)
    assert client.get(f"/api/image-assets/{identifier}/preview").content == preview
    # A cached copy must never substitute for a missing authoritative record.
    with client.app.state.factory.begin() as session:
        session.execute(delete(StoredAsset).where(StoredAsset.id == identifier))
    with pytest.raises(ValueError, match="database"):
        store.path(identifier)
    assert client.get(f"/api/image-assets/{identifier}/preview").status_code == 404


def test_cache_idle_expiration_refreshes_reads_and_protects_active_rendering(client):
    first = upload(client)
    second = upload(client, SVG.replace(b"black", b"red"))
    store = client.app.state.images
    cold, hot = store.path(first), store.path(second)
    old = time.time() - 120
    os.utime(cold, (old, old))
    os.utime(hot, (old, old))
    store.path(second)
    assert hot.stat().st_mtime > old
    with cache_use():
        assert expire(store.root.parent, 60) == 0
        assert cold.exists()
    assert expire(store.root.parent, 60) == 1
    assert not cold.exists() and hot.exists()
    assert store.path(first).read_bytes()
    assert client.get("/api/image-assets").json()


def test_font_cache_is_reconstructed_from_database(client):
    response = client.post("/api/font-assets", content=(FONT_DIR / "NotoSans.ttf").read_bytes())
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    store = client.app.state.fonts
    original = store.path(identifier).read_bytes()
    shutil.rmtree(store.root)
    reloaded = FontStore(store.root, client.app.state.factory)
    assert reloaded.path(identifier).read_bytes() == original
    assert reloaded.metadata(identifier)["render_family"] == response.json()["render_family"]


def test_legacy_import_verifies_bytes_preserves_ids_and_never_reimports_stale_files(
    accounts, tmp_path
):
    admin, _, _ = accounts
    root = tmp_path / "legacy-assets"
    image = ImageStore(root / "images").add(SVG, owner_id="alice", scope="global")
    font = FontStore(root / "fonts").add((FONT_DIR / "NotoSans.ttf").read_bytes(), owner_id="alice")
    portrait = avatar_path(root, "alice")
    portrait.parent.mkdir(parents=True)
    portrait.write_bytes(normalize_avatar(picture()))
    with admin.app.state.factory.begin() as session:
        session.execute(delete(AssetImport))
        import_assets(session, root)
    with admin.app.state.factory() as session:
        stored = session.get(StoredAsset, ("image", image["id"]))
        assert stored.details == image and stored.source == SVG
        assert stored.content == (root / "images" / f"{image['id']}.image").read_bytes()
        assert session.get(StoredAsset, ("font", font["id"])).details == font
        assert read_avatar(session, "alice") == portrait.read_bytes()
        assert avatar_version(session, "alice")
    assert portrait.exists() and (root / "images" / f"{image['id']}.json").exists()
    # Removal after migration is final even though rollback copies are retained.
    with admin.app.state.factory.begin() as session:
        session.execute(delete(StoredAsset))
        import_assets(session, root)
    with admin.app.state.factory() as session:
        assert list(session.scalars(select(StoredAsset))) == []


def test_incomplete_import_rolls_back_and_can_be_retried(client, tmp_path):
    root = tmp_path / "legacy-assets"
    image = ImageStore(root / "images").add(SVG)
    font = FontStore(root / "fonts").add((FONT_DIR / "NotoSans.ttf").read_bytes())
    missing = root / "fonts" / f"{font['id']}.font"
    saved = missing.read_bytes()
    missing.unlink()
    with client.app.state.factory.begin() as session:
        session.execute(delete(AssetImport))
    with pytest.raises(ValueError, match="missing"):
        with client.app.state.factory.begin() as session:
            import_assets(session, root)
    with client.app.state.factory() as session:
        assert session.get(StoredAsset, ("image", image["id"])) is None
        assert session.get(AssetImport, "legacy-files-v1") is None
    missing.write_bytes(saved)
    with client.app.state.factory.begin() as session:
        import_assets(session, root)
    assert client.app.state.images.exists(image["id"])


def test_backup_binary_codec_and_migration_digest_are_byte_exact():
    row = [b"\x00\xff\x80image", b"", None, '{"$label_bytes":"literal JSON column"}']
    restored = json.loads(encode({"row": row}), object_hook=decode_binary)["row"]
    assert restored == row
    assert digest([row]) == digest([restored])
    assert digest([[b"changed"]]) != digest([[b"original"]])


def test_archive_requires_committed_import_and_moves_all_files_without_overwrite(client, tmp_path):
    from app.asset_import import archive_legacy_assets

    root = tmp_path / "assets"
    root.mkdir()
    (root / "original.image").write_bytes(b"original")
    with client.app.state.factory.begin() as session:
        session.execute(delete(AssetImport))
    with pytest.raises(ValueError, match="commit"):
        archive_legacy_assets(client.app.state.factory, root)
    assert root.is_dir()
    with client.app.state.factory.begin() as session:
        session.add(AssetImport(id="legacy-files-v1"))
    archived = archive_legacy_assets(client.app.state.factory, root)
    assert archived is not None and archived.parent == tmp_path / "backups"
    assert (archived / "original.image").read_bytes() == b"original"
    assert not root.exists()
    assert archive_legacy_assets(client.app.state.factory, root) is None
    root.mkdir()
    (root / "later.image").write_bytes(b"later")
    second = archive_legacy_assets(client.app.state.factory, root)
    assert second != archived and (archived / "original.image").exists()


def test_interrupted_archive_retries_without_touching_database_or_source(
    client, tmp_path, monkeypatch
):
    from pathlib import Path

    from app.asset_import import archive_legacy_assets

    root = tmp_path / "assets"
    root.mkdir()
    (root / "original").write_bytes(b"saved")
    rename = Path.rename
    with monkeypatch.context() as patch:

        def failed_move(*args):
            raise OSError("simulated unavailable destination")

        patch.setattr(Path, "rename", failed_move)
        with pytest.raises(OSError, match="destination"):
            archive_legacy_assets(client.app.state.factory, root)
    assert Path.rename is rename
    assert (root / "original").read_bytes() == b"saved"
    archived = archive_legacy_assets(client.app.state.factory, root)
    assert archived is not None and (archived / "original").read_bytes() == b"saved"
    with client.app.state.factory() as session:
        assert session.get(AssetImport, "legacy-files-v1") is not None


def test_startup_commits_import_then_archives_assets_once(tmp_path):
    from alembic import command
    from alembic.config import Config
    from app_client import TestClient
    from conftest import create_test_app, seed_test_printer
    from mock_backend import MockPrinterBackend

    from app.config import Settings

    state = tmp_path / "state"
    legacy = ImageStore(state / "assets" / "images")
    asset = legacy.add(SVG)
    saved = legacy.path(asset["id"]).read_bytes()
    url = f"sqlite:///{state / 'labels.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    seed_test_printer(url)
    for _ in range(2):
        application = create_test_app(
            Settings(database_url=url), {"main": MockPrinterBackend()}, start_worker=False
        )
        with TestClient(application) as running:
            assert not (state / "assets").exists()
            archives = list((state / "backups").glob("assets-*"))
            assert len(archives) == 1
            assert (archives[0] / "images" / f"{asset['id']}.image").read_bytes() == saved
            assert running.app.state.images.path(asset["id"]).read_bytes() == saved


def test_retained_smooth_preview_rehydrates_expired_font_cache(client):
    from app.render import RenderSpec, render_document
    from app.template_schema import TemplateDocument

    font = client.post("/api/font-assets", content=(FONT_DIR / "NotoSans.ttf").read_bytes()).json()
    document = TemplateDocument.model_validate(
        {
            "elements": [
                {
                    "id": "text1",
                    "kind": "text",
                    "font": font["id"],
                    "content": "After expiry",
                    "x": 1,
                    "y": 1,
                    "width": 40,
                    "height": 10,
                }
            ]
        }
    )
    store = client.app.state.fonts
    rendered = render_document(document, {}, RenderSpec(), fonts=store)
    before = rendered.preview("#000000", "#ffffff", smooth=True)
    shutil.rmtree(store.root)
    assert rendered.preview("#000000", "#ffffff", smooth=True) == before


def test_packet_preflight_rejects_oversized_binary_without_serializing_payload():
    from app.binary_json import check_packet_size

    with pytest.raises(ValueError, match="max_allowed_packet") as error:
        check_packet_size([b"private bytes" * 100], 1024)
    assert "private bytes" not in str(error.value)
    check_packet_size([b"private bytes" * 100], 1_000_000)
