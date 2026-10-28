"""Fresh systemd deployment orchestration without root, network or local service changes."""

from types import SimpleNamespace

import pytest

from scripts import install, update


@pytest.fixture
def installer(tmp_path, monkeypatch):
    for name in ("GITHUB_TOKEN", "LABEL_GITHUB_TOKEN", "LABEL_GITHUB_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    args = install.options(["--repository", "example/labels", "--ref", "v1.0.0", "--skip-packages"])
    args.install_dir = tmp_path / "deployment"
    units, rules, runtime = [tmp_path / name for name in ("units", "rules", "systemd")]
    units.mkdir()
    runtime.mkdir()
    monkeypatch.setattr(install, "UNIT_DIRECTORY", units)
    monkeypatch.setattr(install, "RULE_DIRECTORY", rules)
    monkeypatch.setattr(install, "SYSTEMD_DIRECTORY", runtime)
    monkeypatch.setattr(install.sys, "platform", "linux")
    monkeypatch.setattr(install.os, "geteuid", lambda: 0)
    monkeypatch.setattr(install, "system_dependencies", lambda args: None)
    monkeypatch.setattr(
        install,
        "service_identity",
        lambda: SimpleNamespace(pw_uid=123, pw_gid=123, pw_dir=str(tmp_path)),
    )
    monkeypatch.setattr(install, "own_tree", lambda *args, **kwargs: None)
    calls, health = [], []

    def run(command, directory=install.SOURCE, *, capture=False, env=None):
        calls.append((command, directory, env))
        if command[:3] == ["systemctl", "show", install.SERVICE]:
            return "not-found"
        if "clone" in command:
            args.install_dir.mkdir()
            for name in (
                "pyproject.toml",
                "requirements.lock",
                "alembic.ini",
                "frontend/package-lock.json",
            ):
                path = args.install_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
        if command[:5] == ["runuser", "-u", "labels", "--", "npm"] and "build" in command:
            (args.install_dir / "frontend/dist").mkdir()
            (args.install_dir / "frontend/dist/index.html").write_text("built fixture")
        return ""

    monkeypatch.setattr(install, "run", run)
    monkeypatch.setattr(update, "wait_healthy", lambda url, timeout: health.append(url))
    return args, calls, health, units, rules, run


@pytest.mark.parametrize("start", [True, False])
def test_fresh_install_fetches_selected_github_ref_builds_migrates_and_hardens(installer, start):
    args, calls, health, units, rules, _ = installer
    args.no_start = not start
    install.install(args)
    commands = [call[0] for call in calls]
    clone = next(command for command in commands if "clone" in command)
    assert clone[-2:] == ["https://github.com/example/labels.git", str(args.install_dir)]
    assert clone[clone.index("--branch") + 1] == "v1.0.0"
    migration = next(
        index for index, command in enumerate(commands) if command[-2:] == ["upgrade", "head"]
    )
    enable = commands.index(["systemctl", "enable", "labels.service"])
    assert migration < enable
    assert bool(health) is start
    assert (["systemctl", "start", "labels.service"] in commands) is start
    unit = (units / "labels.service").read_text()
    assert "--host 127.0.0.1 --port 8000" in unit
    assert "User=labels\n" in unit and "SupplementaryGroups=labelprinter" in unit
    assert "ProtectSystem=strict" in unit and "NoNewPrivileges=true" in unit
    assert f"ReadWritePaths={args.install_dir}/data" in unit
    assert (args.install_dir / ".env").stat().st_mode & 0o777 == 0o640
    assert (args.install_dir / "data").stat().st_mode & 0o777 == 0o700
    assert (rules / "70-label-printer.rules").read_text() == (
        install.SOURCE / "deploy/70-label-printer.rules"
    ).read_text()


def test_read_only_check_resolves_stable_release_without_installing(installer, monkeypatch):
    args, calls, health, units, _, _ = installer
    args.check, args.ref = True, None
    monkeypatch.setattr(update, "latest_release", lambda repository, token: "v9.0.0")
    install.install(args)
    assert not args.install_dir.exists()
    assert list(units.iterdir()) == []
    assert calls == health == []


def test_existing_installation_and_service_are_never_overwritten(installer):
    args, calls, _, units, _, _ = installer
    args.install_dir.mkdir()
    sentinel = args.install_dir / "data.db"
    sentinel.write_text("preserve")
    with pytest.raises(update.UpdateError, match="already exists"):
        install.install(args)
    assert sentinel.read_text() == "preserve"
    assert calls == []
    args.install_dir = args.install_dir.parent / "other"
    (units / "labels.service").write_text("existing unit")
    with pytest.raises(update.UpdateError, match="already exists"):
        install.install(args)
    assert (units / "labels.service").read_text() == "existing unit"
    assert not args.install_dir.exists()


def test_private_repository_token_is_stored_separately_and_not_in_config_or_commands(
    installer, tmp_path, capsys
):
    args, calls, _, _, _, _ = installer
    token = "github_pat_fixture_only"
    path = tmp_path / "credential"
    path.write_text(token)
    args.github_token_file = path
    install.install(args)
    secret = args.install_dir / "data/github-token"
    assert secret.read_text().strip() == token
    assert secret.stat().st_mode & 0o777 == 0o600
    assert token not in (args.install_dir / ".env").read_text()
    assert "LABEL_GITHUB_TOKEN_FILE=data/github-token" in (args.install_dir / ".env").read_text()
    assert token not in repr([call[0] for call in calls])
    assert token not in capsys.readouterr().out


@pytest.mark.parametrize("stage", ["migration", "health"])
def test_failed_migration_never_starts_and_failed_health_stops_service(
    installer, monkeypatch, stage
):
    args, calls, _, _, _, original = installer

    def failing_run(command, *positional, **kwargs):
        if stage == "migration" and command[-2:] == ["upgrade", "head"]:
            raise update.UpdateError("fixture migration failed")
        return original(command, *positional, **kwargs)

    def unhealthy(*args):
        raise update.UpdateError("fixture health failed")

    monkeypatch.setattr(install, "run", failing_run)
    monkeypatch.setattr(update, "wait_healthy", unhealthy)
    with pytest.raises(update.UpdateError):
        install.install(args)
    commands = [call[0] for call in calls]
    assert (["systemctl", "start", "labels.service"] in commands) is (stage == "health")
    if stage == "health":
        assert commands[-2:] == [
            ["systemctl", "stop", "labels.service"],
            ["systemctl", "disable", "labels.service"],
        ]
    assert args.install_dir.exists()


def test_ipv6_lan_binding_uses_loopback_for_health(installer):
    args, _, health, units, _, _ = installer
    args.host = "::"
    install.install(args)
    assert "--host :: --port 8000" in (units / "labels.service").read_text()
    assert health == ["http://[::1]:8000/api/health"]


@pytest.mark.parametrize(
    "options",
    [
        ["--host", "host.invalid"],
        ["--port", "80"],
        ["--ref", "--upload-pack=bad"],
        ["--public-url", "http://user:password@example.invalid"],
    ],
)
def test_invalid_inputs_are_rejected(options):
    with pytest.raises(SystemExit):
        install.options(options)
