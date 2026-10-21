"""Release updates with real temporary Git repositories and isolated fake runtimes."""

import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import update


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
):
    root, data, previous, newest = deployment
    install = root
    if separate:
        install = root.parent / "copied-installation"
        shutil.copytree(root, install, ignore=shutil.ignore_patterns(".git", "data"))
        shutil.move(str(data), str(install / "storage"))
        data = install / "storage"
    args = update.options(["--mode", mode, "--checkout", str(root), "--install-dir", str(install)])
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
        return "v2.0.0"

    monkeypatch.setattr(update, "latest_release", release)
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
            backup = next(args.backup_dir.iterdir())
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
    if mode == "native":
        assert any(command[1:5] == ["-m", "pip", "install", "-c"] for command in events)
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
