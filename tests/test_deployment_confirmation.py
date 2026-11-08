"""Runtime discovery and consent must precede deployment changes."""

import subprocess

import pytest
from test_install import installer as installer
from test_update import deployment as deployment
from test_update import git, preflight_only

from scripts import install, update


@pytest.mark.parametrize("role", ["main", "companion"])
@pytest.mark.parametrize("mode", ["native", "docker"])
def test_auto_mode_uses_installed_service_or_container(tmp_path, monkeypatch, role, mode):
    if role == "companion":
        (tmp_path / ".env.companion").touch()
    calls = []
    monkeypatch.setattr(update.shutil, "which", lambda name: "/bin/" + name)

    def probe(command, directory):
        calls.append(command)
        if command[0] == "systemctl":
            return f"LoadState={'loaded' if mode == 'native' else 'not-found'}\nWorkingDirectory={tmp_path}"
        return "stopped-container" if mode == "docker" else ""

    monkeypatch.setattr(update, "probe_deployment", probe)
    args = update.options(["--checkout", str(tmp_path), "--project-name", "my-labels"])
    assert args.mode == mode and args.mode_detected
    assert args.role == role
    docker = next(command for command in calls if command[0] == "docker")
    assert "--all" in docker
    assert f"label=com.docker.compose.project.working_dir={tmp_path}" in docker
    assert (
        f"label=com.docker.compose.service={'companion' if role == 'companion' else 'labels'}"
        in docker
    )
    assert "label=com.docker.compose.project=my-labels" in docker


@pytest.mark.parametrize("both", [False, True])
def test_auto_mode_rejects_missing_or_ambiguous_installations(tmp_path, monkeypatch, both):
    # Every checkout ships these; their presence is not installation evidence.
    (tmp_path / "Dockerfile").touch()
    (tmp_path / "docker-compose.yml").touch()
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(update.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(
        update,
        "probe_deployment",
        lambda command, _: (
            f"LoadState=loaded\nWorkingDirectory={tmp_path if both else tmp_path / 'unrelated'}"
            if command[0] == "systemctl"
            else ("container" if both else "")
        ),
    )
    with pytest.raises(update.UpdateError, match="Both native|No installed"):
        update.options(["--checkout", str(tmp_path)])


def test_auto_mode_reports_unavailable_inspection_without_guessing(tmp_path, monkeypatch):
    monkeypatch.setattr(update.shutil, "which", lambda name: "/bin/" + name)

    def failed(*args, **kwargs):
        raise subprocess.TimeoutExpired("probe", 10)

    monkeypatch.setattr(update.subprocess, "run", failed)
    with pytest.raises(update.UpdateError, match="could not inspect systemd, Docker"):
        update.options(["--checkout", str(tmp_path)])


@pytest.mark.parametrize("mode", ["native", "docker"])
def test_explicit_mode_skips_detection(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(
        update, "detect_mode", lambda _: pytest.fail("Override must skip detection")
    )
    args = update.options(["--mode", mode, "--checkout", str(tmp_path)])
    assert args.mode == mode and not args.mode_detected


@pytest.mark.parametrize(
    ("answer", "accepted"),
    [("y", True), (" YES ", True), ("", False), ("no", False), ("anything", False)],
)
def test_confirmation_defaults_to_no(monkeypatch, answer, accepted):
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: True)
    prompts = []

    def reply(prompt):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr("builtins.input", reply)
    assert update.confirm_operation("Proceed?", yes=False) is accepted
    assert prompts == ["Proceed? [y/N] "]


def test_eof_cancels_confirmation(monkeypatch):
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: True)

    def eof(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert not update.confirm_operation("Proceed?", yes=False)


def test_unattended_operation_requires_explicit_yes(monkeypatch):
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Never read a pipe for consent"))
    with pytest.raises(update.UpdateError, match="--yes"):
        update.confirm_operation("Proceed?", yes=False)
    assert update.confirm_operation("Proceed?", yes=True)


@pytest.mark.parametrize("mode", ["native", "docker"])
def test_declined_update_does_not_fetch_backup_or_change_installation(
    deployment, monkeypatch, mode
):
    preflight_only(deployment, monkeypatch)
    root, _, previous, _ = deployment
    monkeypatch.setattr("builtins.input", lambda _: "")
    args = update.options(["--mode", mode, "--checkout", str(root)])
    update.update(args)
    assert git(root, "rev-parse", "HEAD") == previous
    assert not (root / ".git/FETCH_HEAD").exists()
    assert not args.backup_dir.exists()


@pytest.mark.parametrize("check", [False, True])
def test_install_confirmation_precedes_packages_and_files(installer, monkeypatch, check):
    args, calls, health, units, _, _ = installer
    args.yes, args.check = False, check
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input", lambda _: pytest.fail("Check must not prompt") if check else "no"
    )
    monkeypatch.setattr(
        install, "system_dependencies", lambda _: pytest.fail("No package installation")
    )
    install.install(args)
    assert not args.install_dir.exists()
    assert list(units.iterdir()) == [] and health == []
    assert all(command[0] == "systemctl" and command[1] == "show" for command, _, _ in calls)
