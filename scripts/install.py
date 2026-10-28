#!/usr/bin/env python3
"""Install a fresh GitHub release as the native labels systemd service on Debian 13+."""

from __future__ import annotations

import argparse
import grp
import ipaddress
import os
import pwd
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

if sys.version_info < (3, 12):
    raise SystemExit("The installer requires Python 3.12+. Debian 13 provides a suitable Python.")

if __package__:
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path, default=Path("/opt/labels"))
    parser.add_argument(
        "--repository",
        default=update.DEFAULT_REPOSITORY,
        help="GitHub OWNER/REPOSITORY (default: tarobits/label-server)",
    )
    parser.add_argument(
        "--ref",
        help="Explicit branch or tag; otherwise install the latest published stable release",
    )
    parser.add_argument(
        "--github-token-file", type=Path, help="Read a private-repository token from a file"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind address; use 0.0.0.0 for LAN access"
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--public-url", help="Browser-reachable HTTP(S) origin for notification links"
    )
    parser.add_argument(
        "--skip-packages", action="store_true", help="Use already installed system dependencies"
    )
    parser.add_argument(
        "--no-start", action="store_true", help="Install and enable the service without starting it"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Resolve the GitHub version and show the plan without changing anything",
    )
    args = parser.parse_args(argv)
    raw = args.install_dir.absolute()
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(raw)) or len(raw.parts) < 3:
        parser.error(
            "Use a dedicated absolute installation path without spaces or special characters"
        )
    if raw.resolve() != raw:
        parser.error("The installation path must not contain symlinks or '..'")
    args.install_dir = raw
    try:
        args.host = str(ipaddress.ip_address(args.host))
    except ValueError:
        parser.error("--host must be an IPv4 or IPv6 address")
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
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
        parser.error("--public-url must be an HTTP(S) origin without credentials or a path")
    if args.ref and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", args.ref):
        parser.error("--ref must be a branch or tag name")
    return args


def run(
    args: list[str],
    directory: Path = SOURCE,
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    return update.command(args, directory, capture=capture, env=env)


def render_unit(directory: Path, host: str, port: int) -> str:
    # Keep the packaged hardening and USB group; change only installation/bind settings.
    return (SOURCE / "deploy/labels.service").read_text().replace(
        "/opt/labels", str(directory)
    ).replace("--host 0.0.0.0 --port 8000", f"--host {host} --port {port}") + "\n"


def system_dependencies(args: argparse.Namespace) -> None:
    if not args.skip_packages:
        if not shutil.which("apt-get"):
            raise update.UpdateError(
                "Automatic packages require apt-get; provision dependencies and use --skip-packages"
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
            raise update.UpdateError(f"Missing required command: {executable}")
    version = run(["node", "--version"], capture=True).lstrip("v").split(".")
    numbers = tuple(int(part) for part in version[:3])
    if not ((20, 19, 0) <= numbers < (21, 0, 0) or numbers >= (22, 12, 0)):
        raise update.UpdateError(
            "The UI requires Node 20.19+ (20.x) or Node 22.12+. Install a supported Node and retry."
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
        raise update.UpdateError("The labels service account must not be root")
    run(["usermod", "--append", "--groups", "labelprinter", "labels"])
    return user


def own_tree(directory: Path, uid: int, gid: int, *, skip_data: bool = False) -> None:
    os.chown(directory, uid, gid, follow_symlinks=False)
    for root, directories, files in os.walk(directory, followlinks=False):
        if skip_data and Path(root) == directory:
            directories[:] = [name for name in directories if name != "data"]
        for name in [*directories, *files]:
            os.chown(Path(root) / name, uid, gid, follow_symlinks=False)


def install(args: argparse.Namespace) -> None:
    target = args.install_dir
    if target.exists() or target.is_symlink():
        raise update.UpdateError(
            "Installation directory already exists; use scripts/update.py for an existing service"
        )
    repository = args.repository
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise update.UpdateError("Repository must be GitHub OWNER/REPOSITORY")
    if args.github_token_file:
        args.github_token_file = args.github_token_file.resolve()
    token = update.installation_token(args)
    ref = args.ref or update.latest_release(repository, token)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref):
        raise update.UpdateError("Unsupported release tag name")
    print(
        f"Install {repository} at {ref} into {target}; service {SERVICE}; bind {args.host}:{args.port}"
    )
    if args.check:
        print(
            "Plan: install system packages; clone GitHub; create service user and USB group; build; migrate; install udev/systemd; enable; check health."
        )
        return
    if sys.platform != "linux" or os.geteuid() != 0 or not SYSTEMD_DIRECTORY.is_dir():
        raise update.UpdateError(
            "Run with sudo on a Linux host running systemd (Debian 13+ recommended)"
        )
    unit_path = UNIT_DIRECTORY / SERVICE
    if unit_path.exists() or unit_path.is_symlink():
        raise update.UpdateError(
            "labels.service already exists; refusing to replace an existing service"
        )
    if (
        run(["systemctl", "show", SERVICE, "--property=LoadState", "--value"], capture=True)
        != "not-found"
    ):
        raise update.UpdateError("labels.service is already installed; use the updater")
    rule_path = RULE_DIRECTORY / "70-label-printer.rules"
    rule = (SOURCE / "deploy/70-label-printer.rules").read_text()
    if rule_path.is_symlink() or (rule_path.exists() and rule_path.read_text() != rule):
        raise update.UpdateError(
            "An existing USB rule differs; preserve it and resolve the configuration before installation"
        )
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
            "alembic.ini",
            "frontend/package-lock.json",
        ):
            if not (target / filename).is_file():
                raise update.UpdateError(f"Selected GitHub version is missing {filename}")
        # Fresh state only: never import the caller's .env or database.
        data = target / "data"
        data.mkdir(mode=0o700)
        config = (
            f"LABEL_DATABASE_URL=sqlite:///./data/labels.db\n"
            f"LABEL_PUBLIC_URL={args.public_url.rstrip('/')}\n"
            "LABEL_WORKER_INTERVAL_SECONDS=2\nLABEL_CHECK_FOR_UPDATES=true\n"
        )
        if token:
            descriptor = os.open(data / "github-token", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                file.write(token + "\n")
            config += "LABEL_GITHUB_TOKEN_FILE=data/github-token\n"
        descriptor = os.open(target / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(descriptor, "w") as file:
            file.write(config)
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
                ".",
            ]
        )
        as_user(["npm", "ci", "--prefix", "frontend"])
        as_user(["npm", "run", "build", "--prefix", "frontend"])
        if not (target / "frontend/dist/index.html").is_file():
            raise update.UpdateError("Frontend build did not produce frontend/dist/index.html")
        as_user([str(target / ".venv/bin/alembic"), "upgrade", "head"])
        if data.is_symlink() or (target / ".env").is_symlink():
            raise update.UpdateError("Runtime configuration must not be a symlink")
        # Service owns state; installed application code is read-only to it.
        own_tree(target, 0, user.pw_gid, skip_data=True)
        os.chmod(target / ".env", 0o640)
        RULE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(rule)
        unit_path.write_text(render_unit(target, args.host, args.port))
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
            f"Installation failed. Files and any new state are retained at {target}; no existing deployment was replaced.",
            file=sys.stderr,
        )
        raise
    print(
        f"Installed {SERVICE}. Open {args.public_url}; configure printers in the web UI.\n"
        f"First-run setup token: {data / 'auth-setup-token'} (created when the service starts).\n"
        f"Logs: journalctl -u {SERVICE} -f"
    )


def main() -> None:
    try:
        args = options()
        if args.check:
            install(args)
        else:
            if sys.platform != "linux" or os.geteuid() != 0:
                raise update.UpdateError("Run with sudo on a Linux host running systemd")
            # Serialize fresh installs of the fixed service identity.
            with update.update_lock(Path("/run/lock/label-server-install.lock")):
                install(args)
    except (update.UpdateError, OSError, ValueError) as error:
        raise SystemExit(f"Install failed: {error}") from error


if __name__ == "__main__":
    main()
