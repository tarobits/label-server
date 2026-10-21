#!/usr/bin/env python3
"""Update a native or Compose deployment to GitHub's latest published release.

Uses only the standard library so it also works before installing dependencies.
Failures after shutdown leave the application stopped and preserve the backup.
"""

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = "tarobits/label-server"


class UpdateError(Exception):
    pass


def command(
    args: list[str], cwd: Path, *, capture: bool = False, env: dict[str, str] | None = None
) -> str:
    print("+ " + shlex.join(args), flush=True)
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=capture)
    if result.returncode:
        # Captured configuration/inspection output can contain credentials.
        raise UpdateError(f"Command failed (exit {result.returncode}): {shlex.join(args)}")
    return result.stdout.strip() if capture else ""


def github_repository(remote: str) -> str:
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?",
        remote,
    )
    if not match:
        raise UpdateError("origin must be a GitHub HTTPS or SSH repository URL")
    return match[1]


def latest_release(repository: str, token: str | None = None) -> str:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise UpdateError("Repository must be OWNER/REPOSITORY")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "label-server-updater"}
    if token := token or os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/latest", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise UpdateError(
                "No published release found, or repository access is unavailable"
            ) from error
        raise UpdateError(f"GitHub release lookup failed (HTTP {error.code})") from error
    except (OSError, ValueError) as error:
        raise UpdateError("Could not read the latest GitHub release") from error
    tag = release.get("tag_name") if isinstance(release, dict) else None
    if not isinstance(tag, str) or not tag or release.get("draft") or release.get("prerelease"):
        raise UpdateError("GitHub did not return a published stable release tag")
    return tag


def installation_token(args: argparse.Namespace) -> str | None:
    """Read credentials as data, never execute installation configuration."""
    args.github_token_path = None
    values: dict[str, str] = {}
    dotenv = args.install_dir / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            match = re.match(r"\s*(?:export\s+)?(LABEL_GITHUB_TOKEN(?:_FILE)?)\s*=\s*(.*)", line)
            if match:
                try:
                    parts = shlex.split(match[2], comments=True)
                except ValueError as error:
                    raise UpdateError("Invalid GitHub credential setting in .env") from error
                if len(parts) > 1:
                    raise UpdateError("Invalid GitHub credential setting in .env")
                values[match[1]] = parts[0] if parts else ""
    token_file = args.github_token_file or os.environ.get("LABEL_GITHUB_TOKEN_FILE")
    token = os.environ.get("LABEL_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token_file and not token:
        token_file = values.get("LABEL_GITHUB_TOKEN_FILE")
        token = values.get("LABEL_GITHUB_TOKEN")
    if token_file:
        path = Path(token_file)
        if not path.is_absolute():
            path = args.install_dir / path
        args.github_token_path = path.resolve()
        try:
            token = path.read_text().strip()
        except OSError as error:
            raise UpdateError("Cannot read the GitHub token file") from error
        if not token:
            raise UpdateError("The GitHub token file is empty")
    if token and not re.fullmatch(r"[A-Za-z0-9_]+", token):
        raise UpdateError("Invalid GitHub token format")
    return token or None


@contextmanager
def git_credentials(token: str | None) -> Iterator[dict[str, str] | None]:
    """Supply HTTPS credentials without saving them in Git URLs/config or argv."""
    if not token:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="label-update-auth-") as directory:
        helper = Path(directory) / "askpass"
        helper.write_text(
            '#!/bin/sh\ncase "$1" in\n*Username*) printf "%s\\n" x-access-token;;\n'
            '*) printf "%s\\n" "$LABEL_UPDATE_GITHUB_TOKEN";;\nesac\n'
        )
        helper.chmod(0o700)
        yield {
            **os.environ,
            "GIT_ASKPASS": str(helper),
            "GIT_TERMINAL_PROMPT": "0",
            "LABEL_UPDATE_GITHUB_TOKEN": token,
        }


def options(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("native", "docker"))
    parser.add_argument(
        "--checkout",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Git checkout; a missing directory is cloned automatically",
    )
    parser.add_argument(
        "--install-dir",
        type=Path,
        help="Native application directory, if separate from the source checkout",
    )
    parser.add_argument("--repository", help="GitHub OWNER/REPOSITORY (defaults to origin)")
    parser.add_argument("--github-token-file", type=Path, help="File containing a raw GitHub token")
    parser.add_argument(
        "--backup-dir", type=Path, help="Backup parent, outside application/data paths"
    )
    parser.add_argument("--service", default="labels.service")
    parser.add_argument(
        "--compose-file",
        action="append",
        default=[],
        help="Compose file; repeat for USB/local overrides",
    )
    parser.add_argument("--project-name", help="Existing Compose project name, if explicitly set")
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/api/health")
    parser.add_argument("--health-timeout", type=float, default=60)
    parser.add_argument(
        "--check", action="store_true", help="Show the release and plan without changing anything"
    )
    args = parser.parse_args(argv)
    args.checkout = args.checkout.resolve()
    args.install_dir = (args.install_dir or args.checkout).resolve()
    args.backup_dir = (
        args.backup_dir or args.install_dir.parent / f"{args.install_dir.name}-backups"
    ).resolve()
    if args.install_dir != args.checkout and (
        args.install_dir.is_relative_to(args.checkout)
        or args.checkout.is_relative_to(args.install_dir)
    ):
        parser.error("Separate source and installation directories must not be nested")
    if args.health_timeout <= 0:
        parser.error("--health-timeout must be positive")
    if args.mode == "docker" and args.install_dir != args.checkout:
        parser.error("--install-dir is for native deployments; Compose runs from --checkout")
    if not args.service or args.service.startswith("-"):
        parser.error("Invalid service name")
    return args


def compose(args: argparse.Namespace, *tail: str, capture: bool = False) -> str:
    base = ["docker", "compose", "--project-directory", str(args.checkout)]
    if args.project_name:
        base += ["--project-name", args.project_name]
    for filename in args.compose_file or ["docker-compose.yml"]:
        base += ["--file", filename]
    return command([*base, *tail], args.checkout, capture=capture)


def native_configuration(args: argparse.Namespace) -> tuple[Path, str, dict[str, str]]:
    if os.geteuid() != 0:
        raise UpdateError("Native updates must run as root (sudo) to manage systemd and ownership")
    python = args.install_dir / ".venv/bin/python"
    if not python.is_file():
        raise UpdateError(
            "Existing native installation needs .venv/bin/python; this is an updater, not an installer"
        )
    unit = command(
        ["systemctl", "show", args.service, "--property=WorkingDirectory", "--value"],
        args.install_dir,
        capture=True,
    )
    if not unit or Path(unit).resolve() != args.install_dir:
        raise UpdateError("The systemd WorkingDirectory must match --install-dir")
    user = (
        command(
            ["systemctl", "show", args.service, "--property=User", "--value"],
            args.install_dir,
            capture=True,
        )
        or "root"
    )
    # Preserve unit Environment values as well as the existing .env read by Settings.
    unit_env = command(
        ["systemctl", "show", args.service, "--property=Environment", "--value"],
        args.install_dir,
        capture=True,
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("LABEL_")}
    for entry in shlex.split(unit_env):
        key, _, value = entry.partition("=")
        if key.startswith("LABEL_"):
            env[key] = value
    files = command(
        ["systemctl", "show", args.service, "--property=EnvironmentFiles", "--value"],
        args.install_dir,
        capture=True,
    )
    expected = str(args.install_dir / ".env")
    if files and files not in (f"{expected} (ignore_errors=no)", f"{expected} (ignore_errors=yes)"):
        raise UpdateError(
            "Custom systemd EnvironmentFiles are unsupported; use the installation's .env"
        )
    if (args.install_dir / ".env").is_file():
        values = json.loads(
            command(
                [
                    str(python),
                    "-c",
                    "import json; from dotenv import dotenv_values; print(json.dumps(dotenv_values('.env', interpolate=False)))",
                ],
                args.install_dir,
                capture=True,
            )
        )
        env.update(
            {
                key: value
                for key, value in values.items()
                if key.startswith("LABEL_") and value is not None
            }
        )
    code = (
        "import json; from app.config import Settings; from sqlalchemy.engine import make_url; "
        "from pathlib import Path; s=Settings(); u=make_url(s.database_url); "
        "assert u.drivername.startswith('sqlite') and u.database not in (None, ':memory:'); "
        "assert Path(u.database).resolve().is_file(), 'Configured database is missing'; "
        "assert s.frontend_dist.resolve() == Path('frontend/dist').resolve(), 'Custom frontend path unsupported'; "
        "print(json.dumps({'data': str(Path(u.database).resolve().parent), "
        "'lock': str(Path(u.database).resolve().with_suffix('.worker.lock'))}))"
    )
    configuration = json.loads(
        command([str(python), "-c", code], args.install_dir, capture=True, env=env)
    )
    data = Path(configuration["data"])
    args.database_lock = Path(configuration["lock"])
    if not data.is_dir():
        raise UpdateError("Configured data directory is missing")
    return data, user, env


def docker_configuration(args: argparse.Namespace) -> dict[str, Any]:
    identifiers = compose(args, "ps", "--all", "--quiet", "labels", capture=True).splitlines()
    if len(identifiers) != 1:
        raise UpdateError(
            "Expected one existing labels container; check Compose files/project name"
        )
    container = json.loads(
        command(["docker", "inspect", identifiers[0]], args.checkout, capture=True)
    )[0]
    environment = dict(entry.split("=", 1) for entry in container["Config"]["Env"] if "=" in entry)
    url = environment.get("LABEL_DATABASE_URL", "sqlite:///./data/labels.db")
    if not url.startswith("sqlite:///") or "?" in url:
        raise UpdateError("Automatic volume backup requires an ordinary SQLite file URL")
    path = url.removeprefix("sqlite:///")
    database = Path(
        os.path.normpath(
            path if path.startswith("/") else str(Path(container["Config"]["WorkingDir"]) / path)
        )
    )
    candidates = [
        mount
        for mount in container["Mounts"]
        if database.parent.is_relative_to(Path(mount["Destination"]))
    ]
    if not candidates:
        raise UpdateError("Database/assets must be in a persistent Docker volume or bind mount")
    mount = max(candidates, key=lambda item: len(item["Destination"]))
    if mount["Type"] not in ("volume", "bind"):
        raise UpdateError("Unsupported Docker data mount")
    if any(
        other is not mount and Path(other["Destination"]).is_relative_to(Path(mount["Destination"]))
        for other in container["Mounts"]
    ):
        raise UpdateError(
            "Nested data mounts need a separate backup strategy; refusing an incomplete backup"
        )
    return {
        "image": container["Image"],
        "mount": mount,
        "container_image": container["Config"]["Image"],
        "project": container["Config"]["Labels"].get("com.docker.compose.project"),
        "compose": json.loads(compose(args, "config", "--format", "json", capture=True)),
    }


def archive_source(root: Path, target: Path, data: Path | None) -> None:
    excluded = {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }

    def include(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        relative = Path(info.name)
        if set(relative.parts) & excluded or (data and (root / relative).is_relative_to(data)):
            return None
        return info

    with tarfile.open(target, "w:gz") as archive:
        for path in root.iterdir():
            archive.add(path, arcname=path.name, filter=include)


def docker_backup(args: argparse.Namespace, config: dict[str, Any], backup: Path) -> None:
    mount = config["mount"]
    source = mount["Name"] if mount["Type"] == "volume" else mount["Source"]
    data_mount = f"type={mount['Type']},source={source},target=/update-data,readonly"
    if "," in source or "," in str(backup):
        raise UpdateError("Docker backup paths must not contain commas")
    code = (
        "import tarfile; "
        "a=tarfile.open('/update-backup/data.tar.gz','w:gz'); "
        "a.add('/update-data',arcname='data'); a.close()"
    )
    command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--mount",
            data_mount,
            "--mount",
            f"type=bind,source={backup},target=/update-backup",
            "--entrypoint",
            "python",
            config["image"],
            "-c",
            code,
        ],
        args.checkout,
    )


def wait_healthy(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                url, timeout=min(3, max(0.1, deadline - time.monotonic()))
            ) as response:
                if json.load(response).get("healthy") is True:
                    return
        except (OSError, ValueError, AttributeError):
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise UpdateError(f"Health check did not become healthy within {timeout:g} seconds: {url}")


@contextmanager
def update_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise UpdateError("Another update is running for this installation") from error
        yield


def update(args: argparse.Namespace) -> None:
    checkout = args.checkout
    existing = (checkout / ".git").exists()
    if checkout.exists() and not existing:
        raise UpdateError(
            "--checkout must be a Git checkout or a new directory. For a copied native installation, use --checkout /opt/labels-source --install-dir /opt/labels"
        )
    repository = args.repository or DEFAULT_REPOSITORY
    if existing:
        remote = command(["git", "remote", "get-url", "origin"], checkout, capture=True)
        actual = github_repository(remote)
        if args.repository and repository.lower() != actual.lower():
            raise UpdateError("--repository does not match origin")
        repository = actual
        if command(
            ["git", "status", "--porcelain", "--untracked-files=all"], checkout, capture=True
        ):
            raise UpdateError("Checkout has local changes; commit or move them before updating")
        if command(["git", "rev-parse", "--show-toplevel"], checkout, capture=True) != str(
            checkout
        ):
            raise UpdateError("--checkout must be the repository root")
    token = installation_token(args)
    tag = latest_release(repository, token) if token else latest_release(repository)
    for protected in (checkout, args.install_dir):
        if args.backup_dir.is_relative_to(protected):
            raise UpdateError("Backup directory must be outside the checkout and installation")
    print(
        f"Latest release: {repository} {tag}\nMode: {args.mode}\nCheckout: {checkout}\nBackups: {args.backup_dir}",
        flush=True,
    )
    if args.check:
        print(
            "Plan: stop app; back up code/config/data; switch release branch; install/build; migrate; start; verify health."
        )
        return
    required = (
        ["git", "systemctl", "runuser", "npm"] if args.mode == "native" else ["git", "docker"]
    )
    if args.mode == "native" and args.install_dir != checkout:
        required.append("rsync")
    for executable in required:
        if not shutil.which(executable):
            raise UpdateError(f"Required command is missing: {executable}")
    if args.mode == "native":
        data, user, env = native_configuration(args)
        if args.install_dir.is_relative_to(data) or checkout.is_relative_to(data):
            raise UpdateError(
                "Use a dedicated data directory, separate from the application/source directories"
            )
        if args.backup_dir.is_relative_to(data):
            raise UpdateError("Backup directory must be outside configured data")
        docker = None
    else:
        data, user, env = None, "", None
        docker = docker_configuration(args) if existing else None
        if docker is None:
            raise UpdateError("Docker updates require an existing checkout and Compose container")
        # Pin the old project even if a later release changes the top-level Compose name.
        args.project_name = docker["project"] or args.project_name
    args.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = args.install_dir.parent / f".{args.install_dir.name}.update.lock"
    with update_lock(lock_path), ExitStack() as runtime_locks:
        with git_credentials(token) as git_env:
            git = ["git", "-c", "credential.helper="] if token else ["git"]
            if not existing:
                command(
                    [
                        *git,
                        "clone",
                        "--no-checkout",
                        f"https://github.com/{repository}.git",
                        str(checkout),
                    ],
                    checkout.parent,
                    env=git_env,
                    capture=bool(token),
                )
            command(["git", "check-ref-format", f"refs/tags/{tag}"], checkout)
            remote = f"https://github.com/{repository}.git" if token else "origin"
            command(
                [*git, "fetch", "--no-tags", remote, f"refs/tags/{tag}"],
                checkout,
                env=git_env,
                capture=bool(token),
            )
        commit = command(
            ["git", "rev-parse", "--verify", "FETCH_HEAD^{commit}"], checkout, capture=True
        )
        # Refuse a release that tries to overwrite deployment state or use submodules.
        files = command(
            ["git", "ls-tree", "-r", "--name-only", commit], checkout, capture=True
        ).splitlines()
        required_files = {
            "pyproject.toml",
            "requirements.lock",
            "alembic.ini",
            "frontend/package.json",
            "frontend/package-lock.json",
        }
        if args.mode == "docker":
            required_files.add("Dockerfile")
        if missing := required_files - set(files):
            raise UpdateError(
                "Release is missing required deployment files: " + ", ".join(sorted(missing))
            )
        protected = [".env", "data", ".venv", "frontend/node_modules"]
        if args.github_token_path:
            for directory in (checkout, args.install_dir):
                if args.github_token_path.is_relative_to(directory):
                    relative_token = args.github_token_path.relative_to(directory).as_posix()
                    if any(relative_token.startswith(path + "/") for path in files):
                        raise UpdateError(
                            "Release would overwrite the GitHub token file's directory"
                        )
                    protected.append(relative_token)
        if (
            any(
                path == prefix or path.startswith(prefix + "/")
                for path in files
                for prefix in protected
            )
            or ".gitmodules" in files
        ):
            raise UpdateError(
                "Release contains deployment state or submodules; refusing automatic update"
            )
        if data and data.is_relative_to(args.install_dir):
            relative_data = data.relative_to(args.install_dir).as_posix()
            if any(path == relative_data or path.startswith(relative_data + "/") for path in files):
                raise UpdateError("Release contains files inside the configured data directory")
        branch = subprocess.run(
            ["git", "rev-parse", "--verify", "refs/heads/release"],
            cwd=checkout,
            capture_output=True,
            text=True,
        )
        if branch.returncode == 0:
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", branch.stdout.strip(), commit], cwd=checkout
            )
            if ancestor.returncode:
                raise UpdateError(
                    "The release branch diverged from GitHub's latest release; refusing to discard commits"
                )
        old_commit = (
            command(["git", "rev-parse", "HEAD"], checkout, capture=True) if existing else None
        )
        backup = args.backup_dir / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        )
        backup.mkdir(mode=0o700)
        print(f"Backup: {backup}", flush=True)
        metadata = {
            "repository": repository,
            "release": tag,
            "commit": commit,
            "previous_commit": old_commit,
            "mode": args.mode,
            "install_dir": str(args.install_dir),
            "data_dir": str(data) if data else None,
            "docker": docker,
            "status": "preparing",
        }

        def record(status: str) -> None:
            metadata["status"] = status
            (backup / "update.json").write_text(json.dumps(metadata, indent=2) + "\n")

        record("preparing")
        stopped = False
        try:
            stopped = True  # A failed stop can still have changed service state.
            if args.mode == "native":
                command(["systemctl", "stop", args.service], args.install_dir)
                if (
                    subprocess.run(
                        ["systemctl", "is-active", "--quiet", args.service], cwd=args.install_dir
                    ).returncode
                    == 0
                ):
                    raise UpdateError("Service remained active after stop")
            else:
                compose(args, "stop", "labels")
                ids = compose(args, "ps", "--quiet", "labels", capture=True)
                if ids:
                    raise UpdateError("Compose service remained running after stop")
            record("stopped")
            if args.mode == "native" and getattr(args, "database_lock", None):
                try:
                    runtime_locks.enter_context(update_lock(args.database_lock))
                except UpdateError as error:
                    raise UpdateError(
                        "Another process still owns the database; no backup or migration was attempted"
                    ) from error
            archive_data = (
                Path(docker["mount"]["Source"])
                if docker and docker["mount"]["Type"] == "bind"
                else data
            )
            archive_source(args.install_dir, backup / "source.tar.gz", archive_data)
            if (args.install_dir / ".env").is_file():
                shutil.copy2(args.install_dir / ".env", backup / "environment.env")
            if docker:
                compose_backup = backup / "compose-files"
                compose_backup.mkdir(mode=0o700)
                metadata["compose_files"] = []
                for index, filename in enumerate(args.compose_file or ["docker-compose.yml"]):
                    source = Path(filename)
                    if not source.is_absolute():
                        source = checkout / source
                    target = compose_backup / f"{index}-{source.name}"
                    shutil.copy2(source, target)
                    metadata["compose_files"].append(
                        {"original": str(source), "backup": str(target)}
                    )
            if data:
                with tarfile.open(backup / "data.tar.gz", "w:gz") as archive:
                    archive.add(data, arcname="data")
            elif docker:
                docker_backup(args, docker, backup)
            record("backed_up")
            command(["git", "switch", "--force-create", "release", commit], checkout)
            if args.mode == "native":
                if args.install_dir != checkout:
                    excludes = [
                        "--exclude=/.git",
                        "--exclude=/.env",
                        "--exclude=/.venv",
                        "--exclude=/data",
                        "--exclude=/frontend/node_modules",
                        "--exclude=/frontend/dist",
                    ]
                    if args.github_token_path and args.github_token_path.is_relative_to(
                        args.install_dir
                    ):
                        excludes.append(
                            f"--exclude=/{args.github_token_path.relative_to(args.install_dir).as_posix()}"
                        )
                    if data and data.is_relative_to(args.install_dir):
                        excludes.append(
                            f"--exclude=/{data.relative_to(args.install_dir).as_posix()}/"
                        )
                    command(
                        [
                            "rsync",
                            "--archive",
                            "--checksum",
                            "--delete",
                            *excludes,
                            str(checkout) + "/",
                            str(args.install_dir) + "/",
                        ],
                        checkout,
                    )
                python = args.install_dir / ".venv/bin/python"
                command(
                    [str(python), "-m", "pip", "install", "-c", "requirements.lock", "."],
                    args.install_dir,
                    env=env,
                )
                command(["npm", "ci", "--prefix", "frontend"], args.install_dir)
                command(["npm", "run", "build", "--prefix", "frontend"], args.install_dir)
                record("migrating")
                command(
                    [
                        "runuser",
                        "--user",
                        user,
                        "--",
                        str(args.install_dir / ".venv/bin/alembic"),
                        "upgrade",
                        "head",
                    ],
                    args.install_dir,
                    env=env,
                )
                runtime_locks.close()
                command(["systemctl", "daemon-reload"], args.install_dir)
                command(["systemctl", "start", args.service], args.install_dir)
            else:
                compose(args, "build", "--pull", "labels")
                migration = ["run", "--rm", "--no-deps"]
                if (args.install_dir / ".env").is_file():
                    migration += ["--volume", f"{args.install_dir / '.env'}:/srv/labels/.env:ro"]
                record("migrating")
                compose(args, *migration, "labels", "alembic", "upgrade", "head")
                compose(args, "up", "--detach", "--no-deps", "labels")
            wait_healthy(args.health_url, args.health_timeout)
            if args.mode == "native":
                command(["systemctl", "is-active", "--quiet", args.service], args.install_dir)
            elif not compose(args, "ps", "--quiet", "labels", capture=True):
                raise UpdateError("Compose service is not running after startup")
            record("complete")
            print(f"Updated to {tag} ({commit[:12]}). Health check passed. Backup: {backup}")
        except BaseException:
            if stopped:
                try:
                    if args.mode == "native":
                        command(["systemctl", "stop", args.service], args.install_dir)
                    else:
                        compose(args, "stop", "labels")
                except Exception:
                    print(
                        "Could not confirm shutdown; check the service before recovery.",
                        file=sys.stderr,
                    )
                print(
                    f"Update failed; application left stopped. Backup/recovery record: {backup}. Do not start old code against a migrated database; restore code AND data together.",
                    file=sys.stderr,
                )
            try:
                record("failed")
            except OSError:
                print(
                    "Could not save failure status; inspect the backup and service state.",
                    file=sys.stderr,
                )
            raise


def main(argv: list[str] | None = None) -> int:
    try:
        update(options(argv))
    except (UpdateError, OSError, ValueError) as error:
        print(f"Update aborted: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Update interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
