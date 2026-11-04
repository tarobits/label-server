"""Release updates with real temporary Git repositories and isolated fake runtimes."""

import hashlib
import io
import json
import shlex
import shutil
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import update
from scripts.package_frontend import package_frontend


def frontend_bundle(path, commit, extra=None):
    files = {
        "index.html": b"new frontend",
        "sw.js": b"worker",
        "manifest.webmanifest": b"{}",
        "assets/app.js": b"app",
        update.FRONTEND_METADATA: json.dumps({"schema": 1, "commit": commit}).encode(),
    }
    files.update(extra or {})
    with zipfile.ZipFile(path, "w") as bundle:
        for name, value in files.items():
            bundle.writestr(name, value)
    return path


@pytest.mark.parametrize("failure", [None, "migration", "health"])
def test_prebuilt_update_without_npm(deployment, monkeypatch, failure):
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        deployment, monkeypatch, "native", failure, prebuilt=True
    )


def test_prebuilt_separate_install(deployment, monkeypatch):
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        deployment, monkeypatch, "native", None, prebuilt=True, separate=True
    )


@pytest.mark.parametrize(
    "name",
    [
        "../escape.js",
        "/absolute.js",
        "assets/../../escape.js",
        "assets\\escape.js",
        ".env",
        "assets/file.map",
        "private.pem",
    ],
)
def test_prebuilt_rejects_unsafe_files_before_extracting(tmp_path, name):
    archive = frontend_bundle(tmp_path / "bundle.zip", "commit", {name: b"unsafe"})
    destination = tmp_path / "dist"
    with pytest.raises(update.UpdateError):
        update.unpack_frontend(archive, destination, "commit")
    assert not destination.exists()


@pytest.mark.parametrize(
    "invalid", ["symlink", "duplicate", "wrong_commit", "missing", "oversize", "bad_zip"]
)
def test_prebuilt_rejects_invalid_archives(tmp_path, monkeypatch, invalid):
    archive = frontend_bundle(tmp_path / "bundle.zip", "commit")
    if invalid == "symlink":
        with zipfile.ZipFile(archive, "a") as bundle:
            entry = zipfile.ZipInfo("assets/link.js")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(entry, "../../target")
    elif invalid == "duplicate":
        with zipfile.ZipFile(archive, "a") as bundle, pytest.warns(UserWarning):
            bundle.writestr("index.html", "duplicate")
    elif invalid == "missing":
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("index.html", "only")
    elif invalid == "oversize":
        monkeypatch.setattr(update, "MAX_FRONTEND_UNPACKED", 1)
    elif invalid == "bad_zip":
        archive.write_bytes(b"invalid")
    with pytest.raises(update.UpdateError):
        update.unpack_frontend(
            archive, tmp_path / "dist", "other" if invalid == "wrong_commit" else "commit"
        )
    assert not (tmp_path / "dist").exists()


def mock_asset(monkeypatch, content, **changes):
    asset = {
        "id": 123,
        "name": update.FRONTEND_ASSET,
        "size": len(content),
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        "state": "uploaded",
    }
    asset.update(changes)
    monkeypatch.setattr(
        update, "release_request", lambda *args: {"tag_name": "v2.0.0", "assets": [asset]}
    )
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return io.BytesIO(content)

    monkeypatch.setattr(update.urllib.request, "build_opener", lambda *args: Opener())
    return calls


def test_download_verifies_digest_and_authenticates_only_api(tmp_path, monkeypatch):
    calls = mock_asset(monkeypatch, b"archive")
    path = update.download_frontend("example/repo", "v2.0.0", tmp_path, "token")
    assert path.read_bytes() == b"archive"
    assert calls[0].full_url == "https://api.github.com/repos/example/repo/releases/assets/123"
    assert calls[0].get_header("Authorization") == "Bearer token"
    redirected = update.AssetRedirectHandler().redirect_request(
        calls[0],
        None,
        302,
        "Found",
        {},
        "https://release-assets.githubusercontent.com/file?signature=test",
    )
    assert redirected.get_header("Authorization") is None
    with pytest.raises(update.UpdateError, match="redirect"):
        update.AssetRedirectHandler().redirect_request(
            calls[0], None, 302, "Found", {}, "https://example.invalid/file"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"digest": None},
        {"digest": "sha256:" + "0" * 64},
        {"size": 1},
        {"size": 100},
        {"id": "123"},
        {"size": update.MAX_FRONTEND_DOWNLOAD + 1},
    ],
)
def test_invalid_asset_download_is_rejected(tmp_path, monkeypatch, changes):
    mock_asset(monkeypatch, b"archive", **changes)
    with pytest.raises(update.UpdateError):
        update.download_frontend("example/repo", "v2.0.0", tmp_path, None)


def test_missing_asset_has_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        update, "release_request", lambda *args: {"tag_name": "v2.0.0", "assets": []}
    )
    with pytest.raises(update.UpdateError, match="omit --prebuilt-frontend"):
        update.download_frontend("example/repo", "v2.0.0", tmp_path, None)


def test_prebuilt_flag_native_only():
    assert update.options(["--mode", "native", "--prebuilt-frontend"]).prebuilt_frontend
    with pytest.raises(SystemExit):
        update.options(["--mode", "docker", "--prebuilt-frontend"])


def test_packager_round_trip_and_rejects_environment_files(deployment, tmp_path):
    root, _, _, _ = deployment
    (root / "frontend/package.json").write_text('{"version":"3.0.0"}')
    git(root, "commit", "-am", "Prepare release")
    git(root, "tag", "v3.0.0")
    commit = git(root, "rev-parse", "HEAD")
    source = frontend_bundle(tmp_path / "source.zip", commit)
    update.unpack_frontend(source, root / "frontend/dist", commit)
    (root / "frontend/dist" / update.FRONTEND_METADATA).unlink()
    archive = package_frontend(root, tmp_path / "release", "v3.0.0")
    update.unpack_frontend(archive, tmp_path / "unpacked", commit)
    assert (tmp_path / "unpacked/index.html").read_bytes() == b"new frontend"
    assert (tmp_path / "unpacked").stat().st_mode & 0o777 == 0o755
    (root / "frontend/.env").write_text("VITE_NOT_FOR_RELEASE=example")
    with pytest.raises(ValueError, match="environment"):
        package_frontend(root, tmp_path / "release", "v3.0.0")


def preflight_only(deployment, monkeypatch):
    root, data, _, _ = deployment
    monkeypatch.setattr(update, "latest_release", lambda *args: "v2.0.0")
    monkeypatch.setattr(update, "native_configuration", lambda _: (data, "labels", {}))
    monkeypatch.setattr(update, "docker_configuration", lambda _: {"project": "labels"})
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/test/{name}")
    original = update.command

    def command(command, cwd, **kwargs):
        assert command[0] == "git", "No installation or service commands before validation"
        if command[1] == "fetch":
            command = [*command]
            command[command.index("origin")] = str(root)
        elif command[1] == "clone":
            command = [*command]
            command[command.index("https://github.com/tarobits/label-server.git")] = str(root)
        return original(command, cwd, **kwargs)

    monkeypatch.setattr(update, "command", command)


def test_handoff_new_source_checkout_is_clean_and_installation_is_untouched(
    deployment, monkeypatch
):
    root, data, previous, newest = deployment
    old_script = root.parent / "old-updater.py"
    old_script.write_text("# An older standalone updater\n")
    monkeypatch.setattr(update, "__file__", str(old_script))
    preflight_only(deployment, monkeypatch)
    checkout = root.parent / "new-source"
    args = update.options(
        [
            "--mode",
            "native",
            "--checkout",
            str(checkout),
            "--install-dir",
            str(root),
        ]
    )
    update.update(args)
    assert git(root, "rev-parse", "HEAD") == previous
    assert git(checkout, "rev-parse", "HEAD") == newest
    assert not git(checkout, "status", "--porcelain")
    assert (data / "labels.db").read_bytes() == b"original database"
    saved = next(args.backup_dir.glob("updater-*.py"))
    monkeypatch.setattr(update, "__file__", str(saved))
    assert not update.handoff_updater(args, newest, "v2.0.0")


@pytest.mark.parametrize("failure", ["missing", "commit", "digest"])
def test_prebuilt_failure_keeps_service_code_and_data_untouched(deployment, monkeypatch, failure):
    root, data, previous, _ = deployment
    preflight_only(deployment, monkeypatch)
    args = update.options(["--mode", "native", "--checkout", str(root), "--prebuilt-frontend"])

    def download(repository, tag, destination, token):
        if failure == "missing":
            raise update.UpdateError("missing asset")
        if failure == "digest":
            raise update.UpdateError("SHA-256 mismatch")
        return frontend_bundle(destination / update.FRONTEND_ASSET, "wrong-commit")

    monkeypatch.setattr(update, "download_frontend", download)
    with pytest.raises(update.UpdateError):
        update.update(args)
    assert git(root, "rev-parse", "HEAD") == previous
    assert (data / "labels.db").read_bytes() == b"original database"
    assert not list(args.backup_dir.glob("*/update.json"))


@pytest.mark.parametrize("mode", ["native", "docker"])
def test_changed_updater_exits_before_download_and_can_resume(
    deployment, monkeypatch, capsys, mode
):
    root, data, previous, newest = deployment
    git(root, "switch", "--detach", newest)
    revised = Path(update.__file__).read_text() + "\n# A newer release updater.\n"
    (root / "scripts/update.py").write_text(revised)
    git(root, "commit", "-am", "Revise updater")
    newest = git(root, "rev-parse", "HEAD")
    git(root, "tag", "--force", "v2.0.0")
    git(root, "switch", "main")
    with monkeypatch.context() as patch:
        preflight_only((root, data, previous, newest), patch)
        patch.setattr(
            update, "download_frontend", lambda *args: pytest.fail("Download must follow handoff")
        )
        args = update.options(
            [
                "--mode",
                mode,
                "--checkout",
                str(root),
                *(["--prebuilt-frontend"] if mode == "native" else []),
            ]
        )
        update.update(args)
    output = capsys.readouterr().out
    invocation = shlex.split(output.strip().splitlines()[-1])
    if mode == "native":
        assert invocation.pop(0) == "sudo"
    saved = Path(invocation[1])
    assert saved.parent == args.backup_dir
    assert saved.read_text().strip() == revised.strip()
    assert saved.stat().st_mode & 0o777 == 0o600
    resumed = update.options(invocation[2:])
    assert resumed.tag == "v2.0.0" and resumed.prebuilt_frontend == (mode == "native")
    assert resumed.checkout == root and resumed.install_dir == root
    assert git(root, "rev-parse", "HEAD") == previous
    assert not git(root, "status", "--porcelain")
    assert (data / "labels.db").read_bytes() == b"original database"
    assert not list(args.backup_dir.glob("*/update.json"))
    # Simulate the next invocation executing the saved release updater.
    monkeypatch.setattr(update, "__file__", str(saved))
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        (root, data, previous, newest), monkeypatch, mode, None, prebuilt=(mode == "native")
    )


@pytest.fixture(autouse=True)
def no_installation_credentials(monkeypatch):
    for name in ("GITHUB_TOKEN", "LABEL_GITHUB_TOKEN", "LABEL_GITHUB_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)


def git(root, *args):
    return (
        subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE).decode().strip()
    )


@pytest.fixture
def deployment(tmp_path):
    root = tmp_path / "labels"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Updater test")
    git(root, "config", "user.email", "updater@example.invalid")
    (root / ".gitignore").write_text(
        ".venv/\ndata/\n.env\nfrontend/dist/\nfrontend/node_modules/\n"
    )
    (root / "version.txt").write_text("old")
    for filename in (
        "scripts/update.py",
        "pyproject.toml",
        "requirements.lock",
        "alembic.ini",
        "Dockerfile",
        "docker-compose.yml",
        "frontend/package.json",
        "frontend/package-lock.json",
    ):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder")
    (root / "scripts/update.py").write_text(Path(update.__file__).read_text())
    git(root, "add", ".")
    git(root, "commit", "-m", "Previous installation")
    previous = git(root, "rev-parse", "HEAD")
    (root / "version.txt").write_text("new")
    git(root, "commit", "-am", "New release")
    newest = git(root, "rev-parse", "HEAD")
    git(root, "tag", "v2.0.0")
    git(root, "reset", "--hard", previous)
    git(root, "remote", "add", "origin", "https://github.com/tarobits/label-server.git")
    data = root / "data"
    (data / "assets/images").mkdir(parents=True)
    (data / "labels.db").write_bytes(b"original database")
    (data / "assets/images/art.image").write_bytes(b"original image")
    (root / ".env").write_text("LABEL_PUBLIC_URL=http://label-server\n")
    return root, data, previous, newest


@pytest.mark.parametrize("mode", ["native", "docker"])
@pytest.mark.parametrize("failure", [None, "migration", "health"])
def test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
    deployment,
    monkeypatch,
    mode,
    failure,
    metadata_failure=False,
    separate=False,
    token=None,
    token_file=False,
    channel="stable",
    explicit_tag=None,
    prebuilt=False,
):
    root, data, previous, newest = deployment
    install = root
    if separate:
        install = root.parent / "copied-installation"
        shutil.copytree(root, install, ignore=shutil.ignore_patterns(".git", "data"))
        shutil.move(str(data), str(install / "storage"))
        data = install / "storage"
    args = update.options(["--mode", mode, "--checkout", str(root), "--install-dir", str(install)])
    args.channel = channel
    args.tag = explicit_tag
    args.prebuilt_frontend = prebuilt
    if prebuilt:
        dist = install / "frontend/dist"
        dist.mkdir(parents=True)
        (dist / "stale.js").write_text("old asset")
        (dist / "index.html").write_text("old frontend")
    selected_tag = explicit_tag or ("v2.0.0-rc.1" if channel == "beta" else "v2.0.0")
    if selected_tag != "v2.0.0":
        git(root, "tag", selected_tag, newest)
    if token:
        if token_file:
            token_path = install / "credentials/github-token"
            token_path.parent.mkdir()
            token_path.write_text(token)
            setting = "LABEL_GITHUB_TOKEN_FILE=credentials/github-token\n"
        else:
            setting = f"LABEL_GITHUB_TOKEN={token}\n"
        for directory in {root, install}:
            with (directory / ".env").open("a") as file:
                file.write(setting)

    def release(repository, credential=None):
        assert credential == token
        return selected_tag

    def unexpected(*args):
        pytest.fail("Wrong release selection path")

    monkeypatch.setattr(
        update,
        "latest_release",
        release if channel == "stable" and not explicit_tag else unexpected,
    )
    monkeypatch.setattr(
        update, "beta_release", release if channel == "beta" and not explicit_tag else unexpected
    )

    def tagged(repository, tag, credential=None):
        assert tag == explicit_tag
        return release(repository, credential)

    monkeypatch.setattr(update, "tagged_release", tagged if explicit_tag else unexpected)
    monkeypatch.setattr(update.shutil, "which", lambda value: f"/test/{value}")
    monkeypatch.setattr(update, "native_configuration", lambda _: (data, "labels", {}))
    config = {
        "image": "sha256:old",
        "container_image": "labels:old",
        "project": "existing-project",
        "mount": {
            "Type": "volume",
            "Name": "real-existing-data",
            "Destination": "/srv/labels/data",
        },
    }
    monkeypatch.setattr(update, "docker_configuration", lambda _: config)
    original_command = update.command
    original_run = subprocess.run
    events = []
    running = True

    def migrate():
        backup = next(args.backup_dir.glob("*/data.tar.gz"))
        with tarfile.open(backup) as archive:
            assert archive.extractfile("data/labels.db").read() == b"original database"
            assert archive.extractfile("data/assets/images/art.image").read() == b"original image"
        assert (backup.parent / "environment.env").read_text() == (root / ".env").read_text()
        with tarfile.open(backup.parent / "source.tar.gz") as archive:
            assert archive.extractfile("version.txt").read() == b"old"
        assert git(root, "rev-parse", "HEAD") == newest
        (data / "labels.db").write_bytes(b"migrated database")
        if failure == "migration":
            raise update.UpdateError("Migration failed")

    def fake_command(command, cwd, **kwargs):
        nonlocal running
        events.append(command)
        if command[0] == "git":
            if command[1:3] == ["-c", "credential.helper="]:
                assert token
                assert kwargs["env"]["LABEL_UPDATE_GITHUB_TOKEN"] == token
                assert kwargs["capture"] is True
                assert Path(kwargs["env"]["GIT_ASKPASS"]).is_file()
                command = ["git", *command[3:]]
            if command[1] == "fetch":
                command = [*command]
                remote = "https://github.com/tarobits/label-server.git" if token else "origin"
                command[command.index(remote)] = str(root)
            return original_command(command, cwd, **kwargs)
        if command[0] == "rsync":
            assert "--exclude=/storage/" in command
            return original_command(command, cwd, **kwargs)
        if command[:2] == ["systemctl", "stop"]:
            running = False
        elif command[:2] == ["systemctl", "start"]:
            running = True
        elif command[0] == "runuser":
            migrate()
        elif command[:2] == ["docker", "run"]:
            assert "--network" in command and "none" in command
            assert config["image"] in command and "real-existing-data" in " ".join(command)
            backup = next(args.backup_dir.glob("*/update.json")).parent
            with tarfile.open(backup / "data.tar.gz", "w:gz") as archive:
                archive.add(data, arcname="data")
        return ""

    def fake_compose(options, *command, **kwargs):
        nonlocal running
        events.append(["compose", *command])
        assert options.project_name == "existing-project"
        if command[0] == "stop":
            running = False
        elif command[0] == "ps":
            return "container" if running else ""
        elif command[0] == "run":
            assert "--no-deps" in command
            assert command[-4:] == ("labels", "alembic", "upgrade", "head")
            assert f"{root / '.env'}:/srv/labels/.env:ro" in command
            migrate()
        elif command[0] == "up":
            running = True
        return ""

    def fake_run(command, **kwargs):
        if command[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(command, 0 if running else 3)
        return original_run(command, **kwargs)

    def healthy(*_):
        assert running
        if failure == "health":
            raise update.UpdateError("Unhealthy")

    monkeypatch.setattr(update, "command", fake_command)
    monkeypatch.setattr(update, "compose", fake_compose)
    monkeypatch.setattr(update.subprocess, "run", fake_run)
    monkeypatch.setattr(update, "wait_healthy", healthy)
    if prebuilt:

        def download(repository, tag, destination, credential):
            assert running  # Network and validation happen before stopping the service.
            assert tag == selected_tag and credential == token
            return frontend_bundle(destination / update.FRONTEND_ASSET, newest)

        monkeypatch.setattr(update, "download_frontend", download)
        monkeypatch.setattr(
            update.shutil, "which", lambda name: None if name == "npm" else f"/test/{name}"
        )
    if failure:
        with pytest.raises(update.UpdateError):
            update.update(args)
    else:
        update.update(args)
    assert running is (failure is None)
    assert git(root, "branch", "--show-current") == "release"
    assert git(root, "rev-parse", "main") == previous
    assert git(root, "rev-parse", "release") == newest
    assert (install / "version.txt").read_text() == "new"
    if token_file:
        assert token_path.read_text() == token
    record = json.loads(next(args.backup_dir.glob("*/update.json")).read_text())
    assert record["status"] == (
        "migrating" if metadata_failure else "failed" if failure else "complete"
    )
    assert record["previous_commit"] == previous
    assert record["release"] == selected_tag
    if mode == "native":
        assert any(command[1:5] == ["-m", "pip", "install", "-c"] for command in events)
        if prebuilt:
            assert not any(command[0] == "npm" for command in events)
            assert (install / "frontend/dist/index.html").read_bytes() == b"new frontend"
            assert not (install / "frontend/dist/stale.js").exists()
            with tarfile.open(next(args.backup_dir.glob("*/source.tar.gz"))) as archive:
                assert archive.extractfile("frontend/dist/index.html").read() == b"old frontend"
        else:
            assert ["npm", "ci", "--prefix", "frontend"] in events
            assert ["npm", "run", "build", "--prefix", "frontend"] in events


@pytest.mark.parametrize("mode", ["native", "docker"])
def test_private_repository_update_authenticates_fetch_without_saving_token(
    deployment, monkeypatch, capsys, mode
):
    token = "github_pat_privateTest"
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        deployment, monkeypatch, mode, None, token=token
    )
    root = deployment[0]
    assert token not in capsys.readouterr().out
    assert token not in (root / ".git/config").read_text()
    assert "LABEL_UPDATE_GITHUB_TOKEN" not in update.os.environ


def test_separate_native_install_preserves_token_file(deployment, monkeypatch):
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        deployment,
        monkeypatch,
        "native",
        None,
        separate=True,
        token="github_pat_preserved",
        token_file=True,
    )


def test_token_sources_and_relative_file_paths(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('LABEL_GITHUB_TOKEN="github_pat_dotenv" # private\n')
    args = update.options(["--mode", "native", "--checkout", str(tmp_path)])
    assert update.installation_token(args) == "github_pat_dotenv"
    (tmp_path / "token").write_text("github_pat_file\n")
    (tmp_path / ".env").write_text("LABEL_GITHUB_TOKEN_FILE=token\n")
    assert update.installation_token(args) == "github_pat_file"
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_env")
    assert update.installation_token(args) == "github_pat_env"
    monkeypatch.setenv("LABEL_GITHUB_TOKEN", "github_pat_labelenv")
    assert update.installation_token(args) == "github_pat_labelenv"
    args.github_token_file = tmp_path / "token"
    assert update.installation_token(args) == "github_pat_file"
    (tmp_path / "token").write_text("")
    with pytest.raises(update.UpdateError, match="empty"):
        update.installation_token(args)


def test_askpass_supplies_token_only_via_child_environment_and_is_removed():
    token = "github_pat_helperTest"
    with update.git_credentials(token) as env:
        helper = Path(env["GIT_ASKPASS"])
        assert token not in helper.read_text()
        assert (
            subprocess.check_output([str(helper), "Username"], env=env).strip() == b"x-access-token"
        )
        assert subprocess.check_output([str(helper), "Password"], env=env).strip().decode() == token
    assert not helper.exists()


def test_release_lookup_authorizes_private_repository_without_token_in_url(monkeypatch):
    def lookup(request, timeout):
        assert request.get_header("Authorization") == "Bearer github_pat_apiTest"
        assert "github_pat" not in request.full_url
        return io.BytesIO(b'{"tag_name":"v0.1.0"}')

    monkeypatch.setattr(update.urllib.request, "urlopen", lookup)
    assert update.latest_release("tarobits/label-server", "github_pat_apiTest") == "v0.1.0"


def test_dirty_checkout_is_rejected_before_network_or_shutdown(deployment, monkeypatch):
    root, _, _, _ = deployment
    (root / "version.txt").write_text("local work")
    monkeypatch.setattr(update, "latest_release", lambda _: pytest.fail("Must not contact GitHub"))
    with pytest.raises(update.UpdateError, match="local changes"):
        update.update(update.options(["--mode", "native", "--checkout", str(root)]))
    assert (root / "version.txt").read_text() == "local work"


def test_check_only_does_not_fetch_switch_back_up_or_manage_service(deployment, monkeypatch):
    root, _, previous, _ = deployment
    monkeypatch.setattr(update, "latest_release", lambda _: "v2.0.0")
    monkeypatch.setattr(
        update, "native_configuration", lambda _: pytest.fail("No service operations")
    )
    update.update(update.options(["--mode", "native", "--checkout", str(root), "--check"]))
    assert git(root, "rev-parse", "HEAD") == previous
    assert not (root / ".git/FETCH_HEAD").exists()
    assert not (root.parent / "labels-backups").exists()


@pytest.mark.parametrize(
    "value",
    [
        {"tag_name": "v2", "draft": True},
        {"tag_name": "v2", "prerelease": True},
        {},
        [],
        {"tag_name": 9},
    ],
)
def test_latest_release_rejects_invalid_or_unpublished_metadata(monkeypatch, value):
    monkeypatch.setattr(
        update.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(value).encode())
    )
    with pytest.raises(update.UpdateError, match="published stable"):
        update.latest_release("tarobits/label-server")


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/tarobits/label-server.git",
        "git@github.com:tarobits/label-server.git",
        "ssh://git@github.com/tarobits/label-server.git",
    ],
)
def test_repository_resolves_from_github_origin(remote):
    assert update.github_repository(remote) == "tarobits/label-server"


def test_native_archive_excludes_runtime_but_preserves_complete_assets(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    for filename in (
        "app/code.py",
        "frontend/dist/index.html",
        ".venv/bin/python",
        "frontend/node_modules/test",
        "storage/labels.db",
    ):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(filename)
    archive_path = tmp_path / "source.tar.gz"
    update.archive_source(root, archive_path, root / "storage")
    with tarfile.open(archive_path) as archive:
        names = archive.getnames()
    assert "app/code.py" in names and "frontend/dist/index.html" in names
    assert not any(
        ".venv" in name or "node_modules" in name or name.startswith("storage") for name in names
    )


def test_update_lock_blocks_concurrent_run(tmp_path):
    with update.update_lock(tmp_path / "lock"):
        with pytest.raises(update.UpdateError, match="Another update"):
            with update.update_lock(tmp_path / "lock"):
                pytest.fail("Second updater must not enter")


def test_native_config_uses_service_settings_not_callers_environment(tmp_path, monkeypatch):
    root = tmp_path / "labels"
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").touch()
    (root / ".env").write_text("LABEL_DATABASE_URL=sqlite:///data/actual.db\n")
    data = root / "data"
    data.mkdir()
    args = update.options(["--mode", "native", "--checkout", str(root)])
    monkeypatch.setattr(update.os, "geteuid", lambda: 0)
    monkeypatch.setenv("LABEL_DATABASE_URL", "sqlite:///wrong.db")

    def configured(command, cwd, **kwargs):
        if command[0] == "systemctl":
            if "--property=WorkingDirectory" in command:
                return str(root)
            if "--property=User" in command:
                return "labels"
            if "--property=Environment" in command:
                return "LABEL_DATABASE_URL=sqlite:///unit.db"
            return f"{root / '.env'} (ignore_errors=no)"
        if "dotenv_values" in command[-1]:
            return json.dumps({"LABEL_DATABASE_URL": "sqlite:///data/actual.db"})
        assert kwargs["env"]["LABEL_DATABASE_URL"] == "sqlite:///data/actual.db"
        return json.dumps({"data": str(data), "lock": str(data / "actual.worker.lock")})

    monkeypatch.setattr(update, "command", configured)
    actual, user, env = update.native_configuration(args)
    assert actual == data and user == "labels"
    assert env["LABEL_DATABASE_URL"] == "sqlite:///data/actual.db"
    assert args.database_lock == data / "actual.worker.lock"


@pytest.mark.parametrize("nested", [False, True])
def test_docker_discovery_preserves_real_volume_and_rejects_nested_data(
    tmp_path, monkeypatch, nested
):
    args = update.options(["--mode", "docker", "--checkout", str(tmp_path)])
    mounts = [{"Type": "volume", "Name": "actual-data-volume", "Destination": "/srv/labels/data"}]
    if nested:
        mounts.append(
            {
                "Type": "volume",
                "Name": "separate-images",
                "Destination": "/srv/labels/data/assets/images",
            }
        )
    container = {
        "Image": "sha256:old",
        "Config": {
            "Env": ["LABEL_DATABASE_URL=sqlite:////srv/labels/data/labels.db"],
            "WorkingDir": "/srv/labels",
            "Image": "labels:old",
            "Labels": {"com.docker.compose.project": "real-project"},
        },
        "Mounts": mounts,
    }
    monkeypatch.setattr(
        update,
        "compose",
        lambda args, *cmd, **kw: (
            "container-id" if cmd[0] == "ps" else '{"services": {"labels": {}}}'
        ),
    )
    monkeypatch.setattr(update, "command", lambda *a, **kw: json.dumps([container]))
    if nested:
        with pytest.raises(update.UpdateError, match="Nested data mounts"):
            update.docker_configuration(args)
    else:
        config = update.docker_configuration(args)
        assert config["mount"]["Name"] == "actual-data-volume"
        assert config["project"] == "real-project"


def test_backup_metadata_failure_still_stops_application(deployment, monkeypatch):
    # The error handler must attempt shutdown even if it cannot write failure metadata.
    original = Path.write_text

    def failed_metadata(path, text, *args, **kwargs):
        if path.name == "update.json" and '"failed"' in text:
            raise OSError("No disk space")
        return original(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failed_metadata)
    # Exercise the common end-to-end path, injecting a failing health check.
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        deployment, monkeypatch, "native", "health", metadata_failure=True
    )


@pytest.mark.skipif(
    shutil.which("rsync") is None, reason="rsync is a native deployment prerequisite"
)
def test_separate_native_install_preserves_custom_data_and_environment(deployment, monkeypatch):
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        deployment, monkeypatch, "native", None, separate=True
    )


@pytest.mark.parametrize("mode", ["native", "docker"])
@pytest.mark.parametrize(
    "selection", [("beta", None), ("stable", "v2.0.0-rc.1"), ("beta", "v2.0.0")]
)
def test_channel_and_tag_install_the_selected_commit(deployment, monkeypatch, mode, selection):
    channel, tag = selection
    test_updates_exact_tag_preserves_main_and_backups_and_stops_on_failure(
        deployment, monkeypatch, mode, None, channel=channel, explicit_tag=tag
    )


def test_release_selection_options():
    assert update.options(["--mode", "native"]).channel == "stable"
    args = update.options(["--mode", "docker", "--channel", "beta", "--tag", "v2.0.0-rc.1"])
    assert args.channel == "beta"
    assert args.tag == "v2.0.0-rc.1"


@pytest.mark.parametrize(
    "tag", ["", "--force", "../main", "v1..2", "v1.lock", "v1\n", "v1//test", "v1/."]
)
def test_invalid_explicit_tags_are_rejected_before_lookup(tag):
    with pytest.raises(SystemExit):
        update.options(["--mode", "native", "--tag", tag])


def test_unknown_channel_is_rejected():
    with pytest.raises(SystemExit):
        update.options(["--mode", "native", "--channel", "nightly"])


def test_beta_selects_latest_publication_across_pages_and_excludes_drafts(monkeypatch):
    pages = [
        [{"tag_name": "v3-draft", "draft": True}] * 99
        + [{"tag_name": "v1.0.0", "published_at": "2026-10-01T00:00:00Z", "prerelease": False}],
        [
            {"tag_name": "v2.0.0-rc.1", "published_at": "2026-11-01T00:00:00Z", "prerelease": True},
            {"tag_name": "v1.1.0", "published_at": "2026-10-15T00:00:00Z", "prerelease": False},
        ],
    ]
    calls = []

    def lookup(request, timeout):
        calls.append(request.full_url)
        assert request.get_header("Authorization") == "Bearer github_pat_apiTest"
        assert request.full_url.endswith(f"?per_page=100&page={len(calls)}")
        return io.BytesIO(json.dumps(pages[len(calls) - 1]).encode())

    monkeypatch.setattr(update.urllib.request, "urlopen", lookup)
    assert update.beta_release("tarobits/label-server", "github_pat_apiTest") == "v2.0.0-rc.1"
    assert len(calls) == 2


def test_beta_can_select_a_newer_stable_release(monkeypatch):
    releases = [
        {"tag_name": "v2.0.0-rc.1", "published_at": "2026-10-01T00:00:00Z", "prerelease": True},
        {"tag_name": "v2.0.0", "published_at": "2026-11-01T00:00:00Z", "prerelease": False},
    ]
    monkeypatch.setattr(update, "release_request", lambda *args: releases)
    assert update.beta_release("tarobits/label-server") == "v2.0.0"


@pytest.mark.parametrize(
    "response",
    [
        [],
        [{"draft": True}],
        {},
        [{"tag_name": "v1"}],
        [{"tag_name": "v1", "published_at": "invalid"}],
        [{"tag_name": "v1", "published_at": "2026-11-01"}],
    ],
)
def test_beta_rejects_missing_or_invalid_published_releases(monkeypatch, response):
    monkeypatch.setattr(update, "release_request", lambda *args: response)
    with pytest.raises(update.UpdateError):
        update.beta_release("tarobits/label-server")


def test_explicit_tag_uses_encoded_release_endpoint_and_accepts_prereleases(monkeypatch):
    tag = "preview/v2.0.0-rc.1+build.2"

    def lookup(request, timeout):
        assert request.full_url.endswith("/releases/tags/preview%2Fv2.0.0-rc.1%2Bbuild.2")
        assert request.get_header("Authorization") == "Bearer github_pat_apiTest"
        return io.BytesIO(
            json.dumps({"tag_name": tag, "prerelease": True, "draft": False}).encode()
        )

    monkeypatch.setattr(update.urllib.request, "urlopen", lookup)
    assert update.tagged_release("tarobits/label-server", tag, "github_pat_apiTest") == tag


@pytest.mark.parametrize("response", [{"tag_name": "v2", "draft": True}, {"tag_name": "v3"}, {}])
def test_explicit_tag_rejects_drafts_or_mismatched_metadata(monkeypatch, response):
    monkeypatch.setattr(update, "release_request", lambda *args: response)
    with pytest.raises(update.UpdateError):
        update.tagged_release("tarobits/label-server", "v2")


@pytest.mark.parametrize("selection", [["--channel", "beta"], ["--tag", "v2.0.0-rc.1"]])
def test_selected_release_lookup_failure_stops_before_deployment(
    deployment, monkeypatch, selection
):
    root, _, previous, _ = deployment

    def missing(request, timeout):
        raise update.urllib.error.HTTPError(request.full_url, 404, "Not found", {}, None)

    monkeypatch.setattr(update.urllib.request, "urlopen", missing)
    monkeypatch.setattr(
        update, "native_configuration", lambda _: pytest.fail("No service operations")
    )
    with pytest.raises(update.UpdateError, match="No published release"):
        update.update(update.options(["--mode", "native", "--checkout", str(root), *selection]))
    assert git(root, "rev-parse", "HEAD") == previous
    assert not (root / ".git/FETCH_HEAD").exists()
    assert not (root.parent / "labels-backups").exists()


@pytest.mark.parametrize(
    "selection", [["--channel", "beta"], ["--channel", "beta", "--tag", "v2.0.0-rc.1"]]
)
def test_check_resolves_channel_or_tag_without_changing_checkout(
    deployment, monkeypatch, capsys, selection
):
    root, _, previous, _ = deployment
    release = {
        "tag_name": "v2.0.0-rc.1",
        "prerelease": True,
        "published_at": "2026-11-01T00:00:00Z",
    }

    def lookup(repository, path, token):
        assert path == ("/tags/v2.0.0-rc.1" if "--tag" in selection else "?per_page=100&page=1")
        return release if "--tag" in selection else [release]

    monkeypatch.setattr(update, "release_request", lookup)
    update.update(
        update.options(["--mode", "native", "--checkout", str(root), "--check", *selection])
    )
    assert "Selected release: tarobits/label-server v2.0.0-rc.1" in capsys.readouterr().out
    assert git(root, "rev-parse", "HEAD") == previous
    assert not (root / ".git/FETCH_HEAD").exists()
