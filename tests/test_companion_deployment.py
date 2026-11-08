"""Native companion installation, durable update/rollback, and role-specific releases."""

import json
import sqlite3
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest
from assertions import require_value
from test_install import installer as installer
from test_update import deployment as deployment
from test_update import git

from app.deployment import require_role
from scripts import install, update
from scripts.package_frontend import package_frontend


def test_install_companion_uses_small_dependencies_and_one_service(installer, tmp_path, capsys):
    args, calls, health, units, _, _ = installer
    args.role, args.port = "companion", 8001
    args.public_url = "http://localhost:8001"
    args.companion_config = tmp_path / "private-config"
    args.companion_config.write_text(
        "LABEL_COMPANION_SERVER_URL=https://labels.example.com\nLABEL_COMPANION_API_KEY=test-secret\n"
    )
    install.install(args)
    commands = [call[0] for call in calls]
    assert not any("alembic" in " ".join(command) for command in commands)
    assert any(command[-2:] == ["-r", "companion/requirements.txt"] for command in commands)
    assert any("build:companion" in command for command in commands)
    assert any("Journal(s.data_dir" in " ".join(command) for command in commands)
    assert (args.install_dir / update.ROLE_MARKER).read_text() == "companion\n"
    config = args.install_dir / ".env.companion"
    assert config.stat().st_mode & 0o777 == 0o640
    assert "test-secret" in config.read_text()
    assert "test-secret" not in capsys.readouterr().out
    assert "test-secret" not in repr(commands)
    assert not (args.install_dir / ".env").exists()
    unit = (units / "labels.service").read_text()
    assert "/.venv/bin/python -m companion" in unit and "app.main" not in unit
    assert "EnvironmentFile=" + str(config) in unit
    assert health == ["http://127.0.0.1:8001/api/health"]
    # A second role in another directory must not replace the machine's service.
    args.install_dir = tmp_path / "another-install"
    args.role = "main"
    with pytest.raises(update.UpdateError, match="already exists"):
        install.install(args)
    assert not args.install_dir.exists()


@pytest.mark.parametrize("overrides", [False, True])
def test_install_companion_preserves_config_and_only_explicit_overrides(
    installer, tmp_path, capsys, overrides
):
    from dotenv import dotenv_values

    args, _, health, units, _, _ = installer
    source = tmp_path / "station.env"
    original = (
        "# Existing station settings\n"
        "LABEL_COMPANION_SERVER_URL=https://labels.example.com\n"
        "LABEL_COMPANION_API_KEY=fixture-secret\n"
        'LABEL_COMPANION_HOST="::" # Bind all interfaces\n'
        "LABEL_COMPANION_PORT=8123\n"
        "LABEL_COMPANION_PUBLIC_URL=https://station.example.com\n"
        'LABEL_COMPANION_DATA_DIR="station-state"\n'
        "LABEL_COMPANION_LOCK_TIMEOUT_SECONDS=120\n"
    )
    source.write_text(original)
    options = ["--role", "companion", "--companion-config", str(source)]
    if overrides:
        options += [
            "--host",
            "127.0.0.1",
            "--port",
            "8124",
            "--public-url",
            "http://localhost:8124",
        ]
    configured = install.options(options)
    args.role = configured.role
    args.companion_config = source
    args.companion_overrides = configured.companion_overrides
    install.install(args)
    target = args.install_dir / ".env.companion"
    text = target.read_text()
    values = dotenv_values(target, interpolate=False)
    assert values["LABEL_COMPANION_HOST"] == ("127.0.0.1" if overrides else "::")
    assert values["LABEL_COMPANION_PORT"] == ("8124" if overrides else "8123")
    assert values["LABEL_COMPANION_PUBLIC_URL"] == (
        "http://localhost:8124" if overrides else "https://station.example.com"
    )
    assert values["LABEL_COMPANION_DATA_DIR"] == "station-state"
    assert values["LABEL_COMPANION_LOCK_TIMEOUT_SECONDS"] == "120"
    for key in ("HOST", "PORT", "PUBLIC_URL", "DATA_DIR"):
        assert text.count(f"LABEL_COMPANION_{key}=") == 1
    assert source.read_text() == original
    if not overrides:
        assert text == original
    expected_host = "127.0.0.1:8124" if overrides else "[::1]:8123"
    assert health == [f"http://{expected_host}/api/health"]
    assert str(args.install_dir / "station-state") in (units / "labels.service").read_text()
    assert "fixture-secret" not in capsys.readouterr().out


def test_companion_missing_settings_use_defaults_without_duplicate_assignments(tmp_path):
    from io import StringIO

    from dotenv import dotenv_values

    source = tmp_path / "station.env"
    source.write_text(
        "# Keep other settings\nLABEL_COMPANION_PORT=8123\nLABEL_COMPANION_DATA_DIR=state#1"
    )
    args = install.options(["--role", "companion", "--companion-config", str(source)])
    text, data = install.companion_configuration(args)
    values = dotenv_values(stream=StringIO(text), interpolate=False)
    assert values["LABEL_COMPANION_HOST"] == "127.0.0.1"
    assert values["LABEL_COMPANION_PORT"] == "8123"
    assert values["LABEL_COMPANION_PUBLIC_URL"] == "http://localhost:8123"
    assert data == args.install_dir / "state#1"
    assert text.count("LABEL_COMPANION_PORT=") == 1


def test_companion_existing_duplicates_keep_last_effective_value(tmp_path):
    from io import StringIO

    from dotenv import dotenv_values

    source = tmp_path / "station.env"
    source.write_text("LABEL_COMPANION_PORT=8123\n# Keep this comment\nLABEL_COMPANION_PORT=8124")
    args = install.options(["--role", "companion", "--companion-config", str(source)])
    text, _ = install.companion_configuration(args)
    assert text.count("LABEL_COMPANION_PORT=") == 1
    assert dotenv_values(stream=StringIO(text))["LABEL_COMPANION_PORT"] == "8124"
    assert "# Keep this comment\n" in text


def test_custom_companion_state_remains_service_owned(tmp_path, monkeypatch):
    state = tmp_path / "station-state"
    state.mkdir()
    (state / "journal.db").touch()
    (tmp_path / "app.py").touch()
    changed = []
    monkeypatch.setattr(
        install.os, "chown", lambda path, *args, **kwargs: changed.append(Path(path))
    )
    install.own_tree(tmp_path, 0, 123, skip_data=True, state_directory=state)
    assert tmp_path / "app.py" in changed
    assert state not in changed and state / "journal.db" not in changed


def test_role_detection_and_runtime_reject_conflicting_installations(tmp_path):
    assert update.deployment_role(tmp_path) == "main"  # Legacy native installations.
    (tmp_path / ".env.companion").touch()
    assert update.deployment_role(tmp_path) == "companion"
    (tmp_path / update.ROLE_MARKER).write_text("companion\n")
    require_role("companion", tmp_path)
    with pytest.raises(RuntimeError, match="not a main"):
        require_role("main", tmp_path)
    (tmp_path / ".env").touch()
    with pytest.raises(update.UpdateError, match="Conflicting"):
        update.deployment_role(tmp_path)

    (tmp_path / ".env").unlink()
    (tmp_path / update.ROLE_MARKER).write_text("main\n")
    with pytest.raises(update.UpdateError, match="Conflicting"):
        update.deployment_role(tmp_path)


@pytest.mark.parametrize("mismatched", [False, True])
def test_native_discovery_reads_companion_settings_and_verifies_service(
    tmp_path, monkeypatch, mismatched
):
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").touch()
    (tmp_path / ".env.companion").write_text("LABEL_COMPANION_DATA_DIR=station-state\n")
    data = tmp_path / "station-state"
    data.mkdir()
    args = update.options(["--mode", "native", "--checkout", str(tmp_path)])
    monkeypatch.setattr(update.os, "geteuid", lambda: 0)
    monkeypatch.setenv("LABEL_COMPANION_DATA_DIR", "wrong-caller-state")

    def command(command, cwd, **kwargs):
        if command[0] == "systemctl":
            for key, value in {
                "WorkingDirectory": str(tmp_path),
                "ExecStart": "uvicorn app.main:create_app" if mismatched else "python -m companion",
                "User": "labels",
                "Environment": "",
                "EnvironmentFiles": f"{tmp_path / '.env.companion'} (ignore_errors=no)",
            }.items():
                if f"--property={key}" in command:
                    return value
        if "dotenv_values" in command[-1]:
            assert "'.env.companion'" in command[-1]
            return json.dumps({"LABEL_COMPANION_DATA_DIR": "station-state"})
        assert "companion.config" in command[-1] and "sqlalchemy" not in command[-1]
        assert kwargs["env"]["LABEL_COMPANION_DATA_DIR"] == "station-state"
        return json.dumps(
            {"data": str(data), "lock": str(data / "station.lock"), "host": "::", "port": 8123}
        )

    monkeypatch.setattr(update, "command", command)
    if mismatched:
        with pytest.raises(update.UpdateError, match="server role"):
            update.native_configuration(args)
    else:
        actual, user, _ = update.native_configuration(args)
        assert actual == data and user == "labels"
        assert args.database_lock == data / "station.lock"
        assert args.health_url == "http://[::1]:8123/api/health"


def test_companion_docker_discovery_uses_its_journal_volume(tmp_path, monkeypatch):
    (tmp_path / ".env.companion").touch()
    args = update.options(["--mode", "docker", "--checkout", str(tmp_path)])
    assert args.compose_file == ["docker-compose.companion.yml"]
    container = {
        "Image": "sha256:previous",
        "Config": {
            "Env": ["LABEL_COMPANION_DATA_DIR=/srv/labels/data/companion"],
            "WorkingDir": "/srv/labels",
            "Image": "companion:previous",
            "Labels": {"com.docker.compose.project": "station"},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": "station-journal",
                "Destination": "/srv/labels/data/companion",
            }
        ],
    }

    def compose(args, *command, **kwargs):
        if command[0] == "ps":
            assert command[-1] == "companion"
            return "station-id"
        return '{"services":{"companion":{}}}'

    monkeypatch.setattr(update, "compose", compose)
    monkeypatch.setattr(update, "command", lambda *a, **kw: json.dumps([container]))
    config = update.docker_configuration(args)
    assert config["mount"]["Name"] == "station-journal"
    assert config["data_relative"] == "."


def companion_bundle(path, commit):
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in {
            "companion.html": "station",
            "assets/companion.js": "station bundle",
            update.FRONTEND_METADATA: json.dumps(
                {"schema": 1, "commit": commit, "role": "companion"}
            ),
        }.items():
            archive.writestr(name, value)
    return path


def test_companion_release_is_separate_and_cannot_be_installed_as_main(deployment, tmp_path):
    root, _, _, newest = deployment
    archive = companion_bundle(tmp_path / "companion.zip", newest)
    with pytest.raises(update.UpdateError):
        update.unpack_frontend(archive, tmp_path / "wrong-role", newest)
    update.unpack_frontend(archive, tmp_path / "station", newest, "companion")
    assert (tmp_path / "station/companion.html").read_text() == "station"
    assert not (tmp_path / "station/index.html").exists()
    (root / "frontend/package.json").write_text('{"version":"3.0.0"}')
    git(root, "commit", "-am", "test: prepare companion release")
    git(root, "tag", "v3.0.0")
    commit = git(root, "rev-parse", "HEAD")
    companion_bundle(archive, commit)
    dist = root / "frontend/dist-companion"
    update.unpack_frontend(archive, dist, commit, "companion")
    (dist / update.FRONTEND_METADATA).unlink()
    packaged = package_frontend(root, tmp_path / "release", "v3.0.0", "companion")
    assert packaged.name == update.COMPANION_FRONTEND_ASSET
    update.unpack_frontend(packaged, tmp_path / "verified", commit, "companion")


@pytest.mark.parametrize("failure", [None, "dependencies", "build", "start", "health"])
@pytest.mark.parametrize("prebuilt", [False, True])
def test_native_companion_update_preserves_journal_and_rolls_back(
    deployment, monkeypatch, failure, prebuilt
):
    if prebuilt and failure == "build":
        return
    root, data, previous, newest = deployment
    (root / ".env").unlink()
    (root / ".env.companion").write_text("LABEL_COMPANION_API_KEY=private-test-key\n")
    (root / update.ROLE_MARKER).write_text("companion\n")
    journal = data / "journal.db"
    with sqlite3.connect(journal) as db:
        db.execute("CREATE TABLE attempts (id TEXT, phase TEXT)")
        db.execute("INSERT INTO attempts VALUES ('batch-1', 'authorized')")
    original_db = journal.read_bytes()
    args = update.options(["--mode", "native", "--checkout", str(root)])
    args.prebuilt_frontend = prebuilt
    assert args.role == "companion"
    args.database_lock = data / "station.lock"
    args.database_lock.touch()
    monkeypatch.setattr(update, "latest_release", lambda *a: "v2.0.0")
    monkeypatch.setattr(update, "native_configuration", lambda _: (data, "labels", {}))
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/test/{name}")
    original_command, original_run = update.command, subprocess.run
    commands = []
    running = True

    def command(command, cwd, **kwargs):
        nonlocal running
        commands.append(command)
        if command[0] == "git":
            if command[1] == "fetch":
                command = [part if part != "origin" else str(root) for part in command]
            return original_command(command, cwd, **kwargs)
        if command[:2] == ["systemctl", "stop"]:
            running = False
        elif command[:2] == ["systemctl", "start"]:
            running = True
            if (root / "version.txt").read_text() == "new":
                assert (data / update.UPDATE_MARKER).exists()
                # Simulate additive startup schema changes while printing stays paused.
                with sqlite3.connect(journal) as db:
                    db.execute("CREATE TABLE new_schema (id TEXT)")
                if failure == "start":
                    raise update.UpdateError("Startup failed")
        elif command[1:4] == ["-m", "pip", "install"]:
            assert command[-2:] == ["-r", "companion/requirements.txt"]
            (root / ".venv/bin/python").write_text("new runtime")
            if failure == "dependencies":
                raise update.UpdateError("Dependency installation failed")
        elif command[:3] == ["npm", "run", "build:companion"]:
            if failure == "build":
                raise update.UpdateError("Build failed")
        assert "alembic" not in " ".join(command)
        return ""

    def run(command, **kwargs):
        if command[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(command, 0 if running else 3)
        return original_run(command, **kwargs)

    def healthy(url, timeout):
        assert url == "http://127.0.0.1:8001/api/health"
        assert running
        if failure == "health" and (root / "version.txt").read_text() == "new":
            raise update.UpdateError("Unhealthy")

    def download(repository, tag, destination, token, role):
        assert role == "companion" and running
        return companion_bundle(destination / update.COMPANION_FRONTEND_ASSET, newest)

    monkeypatch.setattr(update, "command", command)
    monkeypatch.setattr(update.subprocess, "run", run)
    monkeypatch.setattr(update, "wait_healthy", healthy)
    monkeypatch.setattr(update, "download_frontend", download)
    if failure:
        with pytest.raises(update.UpdateError):
            update.update(args)
        assert git(root, "rev-parse", "HEAD") == previous
        assert journal.read_bytes() == original_db
        assert (root / ".venv/bin/python").read_text() == "original runtime"
    else:
        update.update(args)
        assert git(root, "rev-parse", "HEAD") == newest
        if prebuilt:
            assert (root / "frontend/dist-companion/companion.html").read_text() == "station"
    assert running
    assert (root / ".env.companion").read_text() == "LABEL_COMPANION_API_KEY=private-test-key\n"
    assert (root / update.ROLE_MARKER).read_text() == "companion\n"
    assert not (data / update.UPDATE_MARKER).exists()
    with sqlite3.connect(journal) as db:
        assert db.execute("SELECT * FROM attempts").fetchall() == [("batch-1", "authorized")]
    backup = next(args.backup_dir.glob("*/data.tar.gz"))
    with tarfile.open(backup) as bundle:
        assert require_value(bundle.extractfile("data/journal.db")).read() == original_db
    if prebuilt:
        assert not any(command[0] == "npm" for command in commands)
