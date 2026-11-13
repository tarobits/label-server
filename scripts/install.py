#!/usr/bin/env python3
"""Install a fresh GitHub release as the native labels systemd service on Debian 13+."""

from __future__ import annotations

import argparse
import grp
import ipaddress
import json
import os
import pwd
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if sys.version_info < (3, 12):
    raise SystemExit("The installer requires Python 3.12+. Debian 13 provides a suitable Python.")

if TYPE_CHECKING or __package__:
    from . import update
else:
    import update

SOURCE = Path(__file__).resolve().parents[1]
UNIT_DIRECTORY = Path("/etc/systemd/system")
RULE_DIRECTORY = Path("/etc/udev/rules.d")
SYSTEMD_DIRECTORY = Path("/run/systemd/system")
SERVICE = "labels.service"
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def options(argv: list[str] | None = None) -> argparse.Namespace:
    invocation = list(sys.argv[1:] if argv is None else argv)
    language = update.configure_language(invocation)
    parser = argparse.ArgumentParser(description=update.tr("install.description"))
    parser.add_argument(
        "--language", choices=("en", "de"), default=language, help=update.tr("common.language")
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=update.tr("messages.confirmInstallationWithoutPrompting"),
    )
    parser.add_argument("--install-dir", type=Path, default=Path("/opt/labels"))
    parser.add_argument("--role", choices=("main", "companion"), default="main")
    parser.add_argument(
        "--database-url-file",
        type=Path,
        help=update.tr("messages.mainOnlyPrivateFileContainingTheMariaDBDatabaseURL"),
    )
    parser.add_argument(
        "--companion-config",
        type=Path,
        help=update.tr("messages.privateCompanionEnvironmentFileToCopyIntoTheInstallation"),
    )
    parser.add_argument(
        "--repository",
        default=update.DEFAULT_REPOSITORY,
        help=update.tr("messages.githubOWNERREPOSITORYDefaultTarobitsLabelServer"),
    )
    parser.add_argument(
        "--ref",
        help=update.tr(
            "messages.explicitBranchOrTagOtherwiseInstallTheLatestPublishedStableRelease"
        ),
    )
    parser.add_argument(
        "--github-token-file",
        type=Path,
        help=update.tr("messages.readAPrivateRepositoryTokenFromAFile"),
    )
    parser.add_argument("--host", help=update.tr("messages.bindAddressUse0000ForLANAccess"))
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--public-url", help=update.tr("messages.browserReachableHTTPSOriginForNotificationLinks")
    )
    parser.add_argument(
        "--skip-packages",
        action="store_true",
        help=update.tr("messages.useAlreadyInstalledSystemDependencies"),
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help=update.tr("messages.installAndEnableTheServiceWithoutStartingIt"),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=update.tr("messages.resolveTheGitHubVersionAndShowThePlanWithoutChangingAnything"),
    )
    args = parser.parse_args(invocation)
    if not invocation and sys.stdin.isatty():
        print(update.tr("messages.installationSetupPressEnterToAcceptTheDisplayedDefault"))
        print(update.tr("messages.step1ServiceAndInstallationDirectory"))
        args.role = update.prompt_value(
            update.tr("messages.serverRole"), "main", ("main", "companion")
        )
        args.install_dir = Path(
            update.prompt_value(update.tr("messages.installationDirectory"), "/opt/labels")
        )
        print(update.tr("messages.step2Configuration"))
        if args.role == "companion":
            args.companion_config = Path(
                update.prompt_value(update.tr("messages.privateCompanionConfigurationFile"))
            )
        else:
            database = update.prompt_value(
                update.tr("messages.database"), "sqlite", ("sqlite", "mariadb")
            )
            if database == "mariadb":
                args.database_url_file = Path(
                    update.prompt_value(update.tr("messages.privateDatabaseURLFile"))
                )
            args.host = update.prompt_value(update.tr("messages.bindAddress"), "127.0.0.1")
            while True:
                port = update.prompt_value(update.tr("messages.port"), "8000")
                if port.isdecimal() and 1024 <= int(port) <= 65535:
                    args.port = int(port)
                    break
                print(update.tr("messages.enterAPortBetween1024And65535"))
            args.public_url = update.prompt_value(
                update.tr("messages.publicURL"), f"http://localhost:{args.port}"
            )
        print(update.tr("messages.step3Release"))
        release = update.prompt_value(
            update.tr("messages.releaseSelection"), "stable", ("stable", "specific")
        )
        if release == "specific":
            args.ref = update.prompt_value(update.tr("messages.releaseTagOrBranch"))
        print(update.tr("messages.step4InstallationOptions"))
        args.skip_packages = (
            update.prompt_value(
                update.tr("messages.systemDependencies"), "install", ("install", "existing")
            )
            == "existing"
        )
        args.no_start = (
            update.prompt_value(
                update.tr("messages.startTheServiceAfterInstallation"), "yes", ("yes", "no")
            )
            == "no"
        )
    args.companion_overrides = {
        name: getattr(args, name)
        for name in ("host", "port", "public_url")
        if getattr(args, name) is not None
    }
    args.host = args.host if args.host is not None else "127.0.0.1"
    args.port = args.port if args.port is not None else (8001 if args.role == "companion" else 8000)
    if args.role == "companion" and not args.companion_config and not args.check:
        parser.error(
            update.tr("messages.roleCompanionRequiresCompanionConfigWithTheMainServerURLAndAPIKey")
        )
    if args.role == "main" and args.companion_config:
        parser.error(update.tr("messages.companionConfigIsOnlyForCompanionInstallations"))
    if args.role == "companion" and args.database_url_file:
        parser.error(update.tr("messages.companionsUseTheirLocalSQLiteJournal"))
    if args.companion_config:
        args.companion_config = args.companion_config.resolve()
    raw = args.install_dir.absolute()
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(raw)) or len(raw.parts) < 3:
        parser.error(
            update.tr(
                "messages.useADedicatedAbsoluteInstallationPathWithoutSpacesOrSpecialCharacters"
            )
        )
    if raw.resolve() != raw:
        parser.error(update.tr("messages.theInstallationPathMustNotContainSymlinksOr"))
    args.install_dir = raw
    try:
        validate_network(args)
    except update.UpdateError as error:
        parser.error(str(error))
    if args.ref and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", args.ref):
        parser.error(update.tr("messages.refMustBeABranchOrTagName"))
    return args


def validate_network(args: argparse.Namespace) -> None:
    try:
        args.host = str(ipaddress.ip_address(args.host))
    except ValueError:
        raise update.UpdateError(update.tr("messages.hostMustBeAnIPv4OrIPv6Address"))
    if not 1024 <= args.port <= 65535:
        raise update.UpdateError(update.tr("messages.portMustBeBetween1024And65535"))
    args.public_url = args.public_url or f"http://localhost:{args.port}"
    origin = urlsplit(args.public_url)
    if (
        origin.scheme not in ("http", "https")
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
        or any(char.isspace() for char in args.public_url)
    ):
        raise update.UpdateError(
            update.tr("messages.publicUrlMustBeAnHTTPSOriginWithoutCredentialsOrAPath")
        )


def companion_configuration(args: argparse.Namespace) -> tuple[str, Path]:
    """Keep supplied settings, overriding only explicit installer options."""
    source = args.companion_config.read_text()
    defaults = {
        "LABEL_COMPANION_HOST": "127.0.0.1",
        "LABEL_COMPANION_PORT": "8001",
        "LABEL_COMPANION_PUBLIC_URL": "http://localhost:8001",
        "LABEL_COMPANION_DATA_DIR": "data/companion",
    }
    values: dict[str, str] = {}
    existing: dict[str, str] = {}
    lines = source.splitlines(keepends=True)
    keys: dict[int, str] = {}
    for index, line in enumerate(lines):
        match = re.match(r"\s*(?:export\s+)?(LABEL_COMPANION_\w+)\s*=\s*(.*)", line)
        if not match or match[1] not in defaults:
            continue
        key = match[1]
        try:
            # Unquoted '#' inside a path is literal; comments follow whitespace.
            raw = match[2].strip()
            if raw.startswith(("'", '"')):
                parsed = shlex.split(raw, comments=True)
            else:
                parsed = [re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()] if raw else []
        except ValueError:
            raise update.UpdateError(
                update.tr("progress.invalidCompanionSetting", key=key)
            ) from None
        if len(parsed) != 1 or any(ord(char) < 32 for char in parsed[0]):
            raise update.UpdateError(update.tr("progress.invalidCompanionSetting", key=key))
        values[key] = parsed[0]
        existing[key] = line
        keys[index] = key
    overrides = {
        "LABEL_COMPANION_" + name.upper(): str(value)
        for name, value in args.companion_overrides.items()
    }
    effective = defaults | values | overrides
    if "LABEL_COMPANION_PUBLIC_URL" not in values | overrides:
        effective["LABEL_COMPANION_PUBLIC_URL"] = (
            f"http://localhost:{effective['LABEL_COMPANION_PORT']}"
        )
    args.host = effective["LABEL_COMPANION_HOST"]
    try:
        args.port = int(effective["LABEL_COMPANION_PORT"])
    except ValueError:
        raise update.UpdateError(
            update.tr("messages.invalidLABELCOMPANIONPORTInCompanionConfiguration")
        ) from None
    args.public_url = effective["LABEL_COMPANION_PUBLIC_URL"]
    validate_network(args)
    data = (args.install_dir / effective["LABEL_COMPANION_DATA_DIR"]).resolve()
    if data == args.install_dir or data in args.install_dir.parents:
        raise update.UpdateError(update.tr("messages.companionDataMustUseADedicatedStateDirectory"))
    result: list[str] = []
    emitted: set[str] = set()
    for index, line in enumerate(lines):
        key = keys.get(index)
        if key is None:
            result.append(line)
        elif key not in emitted:
            result.append(
                f"{key}={json.dumps(effective[key])}\n"
                if key in overrides
                else existing[key].rstrip("\r\n") + "\n"
            )
            emitted.add(key)
    text = "".join(result)
    if text and not text.endswith("\n"):
        text += "\n"
    for key in defaults:
        if key not in emitted:
            text += f"{key}={json.dumps(effective[key])}\n"
    return text, data


def run(
    args: list[str],
    directory: Path = SOURCE,
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    return update.command(args, directory, capture=capture, env=env)


def render_unit(
    directory: Path, host: str, port: int, role: str = "main", state_directory: Path | None = None
) -> str:
    # Keep the packaged hardening and USB group; change only installation/bind settings.
    unit = (SOURCE / "deploy/labels.service").read_text().replace(
        "/opt/labels", str(directory)
    ).replace("--host 0.0.0.0 --port 8000", f"--host {host} --port {port}") + "\n"
    if role == "companion":
        unit = unit.replace(
            "Description=Label printer server", "Description=Label printer companion"
        )
        unit = unit.replace(
            f"EnvironmentFile={directory}/.env", f"EnvironmentFile={directory}/.env.companion"
        )
        unit = unit.replace(
            f"ExecStart={directory}/.venv/bin/uvicorn app.main:create_app --factory --host {host} --port {port}",
            f"ExecStart={directory}/.venv/bin/python -m companion",
        )
    if state_directory and not state_directory.is_relative_to(directory / "data"):
        path = json.dumps(str(state_directory).replace("%", "%%"), ensure_ascii=False)
        unit = unit.replace(
            f"ReadWritePaths={directory}/data", f"ReadWritePaths={directory}/data {path}"
        )
    return unit


def system_dependencies(args: argparse.Namespace) -> None:
    if not args.skip_packages:
        if not shutil.which("apt-get"):
            raise update.UpdateError(
                update.tr(
                    "messages.automaticPackagesRequireAptGetProvisionDependenciesAndUseSkipPackages"
                )
            )
        env = {"PATH": SAFE_PATH, "DEBIAN_FRONTEND": "noninteractive"}
        run(["apt-get", "update"], env=env)
        run(
            [
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                "git",
                "ca-certificates",
                "python3-venv",
                "nodejs",
                "npm",
                "libusb-1.0-0",
                "usbutils",
                "udev",
            ],
            env=env,
        )
    for executable in (
        "git",
        "node",
        "npm",
        "systemctl",
        "udevadm",
        "runuser",
        "useradd",
        "groupadd",
        "usermod",
    ):
        if not shutil.which(executable):
            raise update.UpdateError(
                update.tr("progress.missingInstallCommand", command=executable)
            )
    version = run(["node", "--version"], capture=True).lstrip("v").split(".")
    numbers = tuple(int(part) for part in version[:3])
    if not ((20, 19, 0) <= numbers < (21, 0, 0) or numbers >= (22, 12, 0)):
        raise update.UpdateError(
            update.tr("messages.theUIRequiresNode201920XOrNode2212InstallASupportedNodeAndRetry")
        )


def service_identity() -> pwd.struct_passwd:
    try:
        grp.getgrnam("labelprinter")
    except KeyError:
        run(["groupadd", "--system", "labelprinter"])
    try:
        user = pwd.getpwnam("labels")
    except KeyError:
        run(
            [
                "useradd",
                "--system",
                "--user-group",
                "--create-home",
                "--home-dir",
                "/var/lib/labels",
                "--shell",
                "/usr/sbin/nologin",
                "labels",
            ]
        )
        user = pwd.getpwnam("labels")
    if user.pw_uid == 0:
        raise update.UpdateError(update.tr("messages.theLabelsServiceAccountMustNotBeRoot"))
    run(["usermod", "--append", "--groups", "labelprinter", "labels"])
    return user


def own_tree(
    directory: Path,
    uid: int,
    gid: int,
    *,
    skip_data: bool = False,
    state_directory: Path | None = None,
) -> None:
    os.chown(directory, uid, gid, follow_symlinks=False)
    for root, directories, files in os.walk(directory, followlinks=False):
        if skip_data:
            directories[:] = [
                name
                for name in directories
                if Path(root) / name not in (directory / "data", state_directory)
            ]
        for name in [*directories, *files]:
            os.chown(Path(root) / name, uid, gid, follow_symlinks=False)


def install(args: argparse.Namespace) -> None:
    target = args.install_dir
    if target.exists() or target.is_symlink():
        raise update.UpdateError(
            update.tr(
                "messages.installationDirectoryAlreadyExistsUseScriptsUpdatePyForAnExistingService"
            )
        )
    companion_config = None
    companion_data = None
    if args.role == "companion" and (args.companion_config or not args.check):
        if not args.companion_config or not args.companion_config.is_file():
            raise update.UpdateError(update.tr("messages.aReadableCompanionConfigFileIsRequired"))
        companion_config, companion_data = companion_configuration(args)
    database_url = None
    if args.database_url_file:
        database_url = args.database_url_file.read_text().strip()
        parsed = urlsplit(database_url)
        if (
            parsed.scheme != "mariadb+pymysql"
            or not parsed.hostname
            or not parsed.path.strip("/")
            or parsed.fragment
            or any(char.isspace() for char in database_url)
        ):
            raise update.UpdateError(
                update.tr(
                    "messages.theDatabaseURLFileMustContainAMariadbPymysqlURLWithAnExistingDatabaseName"
                )
            )
    repository = args.repository
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise update.UpdateError(update.tr("messages.repositoryMustBeGitHubOWNERREPOSITORY"))
    if args.github_token_file:
        args.github_token_file = args.github_token_file.resolve()
    token = update.installation_token(args)
    ref = args.ref or update.latest_release(repository, token)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref):
        raise update.UpdateError(update.tr("messages.unsupportedReleaseTagName"))
    print(
        update.tr(
            "progress.installSelection",
            repository=repository,
            ref=ref,
            target=target,
            role=args.role,
            service=SERVICE,
            host=args.host,
            port=args.port,
        )
    )
    print(update.tr("progress.database", database="MariaDB" if database_url else "SQLite"))
    print(
        update.tr(
            "progress.installPlan",
            role=args.role,
            packages=update.tr(
                "progress.existingPackages" if args.skip_packages else "progress.installPackages"
            ),
            start=update.tr("progress.leaveStopped" if args.no_start else "progress.startHealth"),
        )
    )
    if args.check:
        return
    if sys.platform != "linux" or os.geteuid() != 0 or not SYSTEMD_DIRECTORY.is_dir():
        raise update.UpdateError(
            update.tr("messages.runWithSudoOnALinuxHostRunningSystemdDebian13Recommended")
        )
    unit_path = UNIT_DIRECTORY / SERVICE
    if unit_path.exists() or unit_path.is_symlink():
        raise update.UpdateError(
            update.tr("messages.labelsServiceAlreadyExistsRefusingToReplaceAnExistingService")
        )
    if (
        run(["systemctl", "show", SERVICE, "--property=LoadState", "--value"], capture=True)
        != "not-found"
    ):
        raise update.UpdateError(update.tr("messages.labelsServiceIsAlreadyInstalledUseTheUpdater"))
    rule_path = RULE_DIRECTORY / "70-label-printer.rules"
    rule = (SOURCE / "deploy/70-label-printer.rules").read_text()
    if rule_path.is_symlink() or (rule_path.exists() and rule_path.read_text() != rule):
        raise update.UpdateError(
            update.tr(
                "messages.anExistingUSBRuleDiffersPreserveItAndResolveTheConfigurationBeforeInstallation"
            )
        )
    if not update.confirm_operation(
        update.tr("progress.confirmInstall", role=args.role, ref=ref), yes=args.yes
    ):
        return
    os.umask(0o022)
    system_dependencies(args)
    user = service_identity()
    target.parent.mkdir(parents=True, exist_ok=True)
    enabled = False
    try:
        with update.git_credentials(token) as env:
            clone = ["git"] + (["-c", "credential.helper="] if token else [])
            run(
                [
                    *clone,
                    "clone",
                    "--branch",
                    ref,
                    "--single-branch",
                    f"https://github.com/{repository}.git",
                    str(target),
                ],
                target.parent,
                env=env,
            )
        for filename in (
            "pyproject.toml",
            "requirements.lock",
            "companion/requirements.txt" if args.role == "companion" else "alembic.ini",
            "frontend/package-lock.json",
        ):
            if not (target / filename).is_file():
                raise update.UpdateError(
                    update.tr("progress.missingReleaseFile", filename=filename)
                )
        if (
            companion_data is not None
            and companion_data.is_relative_to(target)
            and companion_data.exists()
        ):
            raise update.UpdateError(
                update.tr("messages.companionStateDirectoryOverlapsTheInstalledSource")
            )
        # Fresh state only: never import the caller's .env or database.
        data = target / "data"
        data.mkdir(mode=0o700)
        config = (
            f"LABEL_DATABASE_URL=sqlite:///./data/labels.db\n"
            f"LABEL_PUBLIC_URL={args.public_url.rstrip('/')}\n"
            "LABEL_WORKER_INTERVAL_SECONDS=2\nLABEL_CHECK_FOR_UPDATES=true\n"
        )
        if database_url:
            config = config.replace(
                "LABEL_DATABASE_URL=sqlite:///./data/labels.db",
                "LABEL_DATABASE_URL=" + json.dumps(database_url),
            )
            config += "LABEL_DATA_DIR=./data\n"
        config_file = ".env.companion" if args.role == "companion" else ".env"
        if args.role == "companion":
            assert companion_config is not None
            config = companion_config
        if token:
            descriptor = os.open(data / "github-token", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                file.write(token + "\n")
            config += "LABEL_GITHUB_TOKEN_FILE=data/github-token\n"
        descriptor = os.open(target / config_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(descriptor, "w") as file:
            file.write(config)
        (target / update.ROLE_MARKER).write_text(args.role + "\n")
        own_tree(target, user.pw_uid, user.pw_gid)
        build_env = {
            "PATH": SAFE_PATH,
            "HOME": user.pw_dir,
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        def as_user(command: list[str]) -> None:
            run(["runuser", "-u", "labels", "--", *command], target, env=build_env)

        as_user([sys.executable, "-m", "venv", ".venv"])
        as_user(
            [
                str(target / ".venv/bin/python"),
                "-m",
                "pip",
                "install",
                "-c",
                "requirements.lock",
                *(["-r", "companion/requirements.txt"] if args.role == "companion" else ["."]),
            ]
        )
        as_user(["npm", "ci", "--prefix", "frontend"])
        as_user(
            [
                "npm",
                "run",
                "build:companion" if args.role == "companion" else "build",
                "--prefix",
                "frontend",
            ]
        )
        entry = (
            "frontend/dist-companion/companion.html"
            if args.role == "companion"
            else "frontend/dist/index.html"
        )
        if not (target / entry).is_file():
            raise update.UpdateError(update.tr("progress.missingFrontend", entry=entry))
        if args.role == "companion":
            as_user(
                [
                    str(target / ".venv/bin/python"),
                    "-c",
                    (
                        "from companion.config import Settings; from companion.journal import Journal; "
                        "s=Settings(); Journal(s.data_dir / 'journal.db'); "
                        "(s.data_dir / 'station.lock').touch(mode=0o600)"
                    ),
                ]
            )
        else:
            as_user([str(target / ".venv/bin/alembic"), "upgrade", "head"])
            if database_url:
                as_user(
                    [
                        str(target / ".venv/bin/python"),
                        "-c",
                        "from pathlib import Path; Path('data/server.worker.lock').touch(mode=0o600)",
                    ]
                )
        if data.is_symlink() or (target / config_file).is_symlink():
            raise update.UpdateError(update.tr("messages.runtimeConfigurationMustNotBeASymlink"))
        # Service owns state; installed application code is read-only to it.
        own_tree(target, 0, user.pw_gid, skip_data=True, state_directory=companion_data)
        os.chmod(target / config_file, 0o640)
        RULE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(rule)
        unit_path.write_text(render_unit(target, args.host, args.port, args.role, companion_data))
        run(["udevadm", "control", "--reload-rules"])
        run(
            [
                "udevadm",
                "trigger",
                "--subsystem-match=usb",
                "--attr-match=idVendor=04f9",
                "--attr-match=idProduct=20af",
            ]
        )
        run(["systemctl", "daemon-reload"])
        enabled = True
        run(["systemctl", "enable", SERVICE])
        if not args.no_start:
            run(["systemctl", "start", SERVICE])
            address = ipaddress.ip_address(args.host)
            host = (
                ("::1" if address.version == 6 else "127.0.0.1")
                if address.is_unspecified
                else str(address)
            )
            host = f"[{host}]" if address.version == 6 else host
            update.wait_healthy(f"http://{host}:{args.port}/api/health", 60)
    except Exception:
        if enabled:
            run(["systemctl", "stop", SERVICE])
            run(["systemctl", "disable", SERVICE])
        print(
            update.tr("progress.installRetained", target=target),
            file=sys.stderr,
        )
        raise
    if args.role == "companion":
        print(update.tr("progress.companionInstalled", service=SERVICE, url=args.public_url))
        return
    print(
        update.tr(
            "progress.mainInstalled",
            service=SERVICE,
            url=args.public_url,
            tokenFile=data / "auth-setup-token",
        )
    )


def main() -> None:
    try:
        args = options()
        if args.check:
            install(args)
        else:
            if sys.platform != "linux" or os.geteuid() != 0:
                raise update.UpdateError(
                    update.tr("messages.runWithSudoOnALinuxHostRunningSystemd")
                )
            # Serialize fresh installs of the fixed service identity.
            with update.update_lock(Path("/run/lock/label-server-install.lock")):
                install(args)
    except (update.UpdateError, OSError, ValueError) as error:
        raise SystemExit(update.tr("progress.installFailed", error=error)) from error
    except KeyboardInterrupt:
        print(update.tr("messages.installationInterrupted"), file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
