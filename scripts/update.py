#!/usr/bin/env python3
"""Update a native or Compose deployment to a published GitHub release.

Uses only the standard library so it also works before installing dependencies.
Failures restore the previous deployment; failed recovery leaves it stopped.
"""

import argparse
import ast
import fcntl
import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Event, Thread
from typing import Any

DEFAULT_REPOSITORY = "tarobits/label-server"
FRONTEND_ASSET = "label-server-frontend.zip"
COMPANION_FRONTEND_ASSET = "label-companion-frontend.zip"
ROLE_MARKER = ".label-server-role"
FRONTEND_METADATA = "frontend-build.json"
MAX_FRONTEND_DOWNLOAD = 64 * 1024 * 1024
MAX_FRONTEND_UNPACKED = 256 * 1024 * 1024
UPDATE_MARKER = ".update-in-progress"
DEPLOYMENT_LANGUAGE_BUNDLE = "lang/deployment.json"
_deployment_root = Path(__file__).resolve().parents[1]
_deployment_language = "en"
_deployment_messages: dict[str, Any] | None = None


def configure_language(invocation: list[str]) -> str:
    """Select a locale without importing the application or changing unattended behavior."""
    global _deployment_language, _deployment_messages
    locale = next(
        (os.environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(key)), "en"
    )
    selected = "de" if re.split(r"[-_.@]", locale.lower())[0] == "de" else "en"
    for index, argument in enumerate(invocation):
        if argument.startswith("--language="):
            selected = argument.split("=", 1)[1]
        elif argument == "--language" and index + 1 < len(invocation):
            selected = invocation[index + 1]
    _deployment_language = selected if selected in {"en", "de"} else "en"
    if _deployment_messages is None:
        _deployment_messages = deployment_catalog(load_deployment_bundle())
    return _deployment_language


def load_deployment_bundle() -> str:
    """Download a missing bundle after an older updater copied only this script.

    The old handoff leaves the selected release in FETCH_HEAD. Read only from a
    commit whose updater matches the running copy. Validate the download against
    that Git object before publishing it, without switching the live checkout.
    """
    try:
        return (_deployment_root / DEPLOYMENT_LANGUAGE_BUNDLE).read_text(encoding="utf-8")
    except FileNotFoundError as missing:
        source = _deployment_root / "scripts/update.py"
        if not source.is_file():
            raise missing

        def git(*arguments: str) -> str:
            return subprocess.check_output(
                ["git", *arguments],
                cwd=_deployment_root,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                timeout=10,
            ).strip()

        for reference in ("FETCH_HEAD", "HEAD"):
            try:
                commit = git("rev-parse", "--verify", reference + "^{commit}")
                if (
                    git("show", f"{commit}:scripts/update.py")
                    != source.read_text(encoding="utf-8").strip()
                ):
                    continue
                expected = git("show", f"{commit}:{DEPLOYMENT_LANGUAGE_BUNDLE}")
                remote = git("remote", "get-url", "origin")
            except (OSError, subprocess.SubprocessError):
                continue
            match = re.fullmatch(
                r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?",
                remote,
            )
            if not match or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
                raise missing
            target = _deployment_root / DEPLOYMENT_LANGUAGE_BUNDLE
            if target.is_symlink() or target.parent.is_symlink():
                raise ValueError("Unsafe deployment language bundle path")
            request = urllib.request.Request(
                f"https://raw.githubusercontent.com/{match[1]}/{commit}/{DEPLOYMENT_LANGUAGE_BUNDLE}",
                headers={"User-Agent": "label-server-updater"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                downloaded = response.read(1024 * 1024 + 1)
            if len(downloaded) > 1024 * 1024:
                raise ValueError("Invalid deployment language bundle")
            bundle = downloaded.decode("utf-8")
            deployment_catalog(bundle)
            if bundle.strip() != expected:
                raise ValueError("Deployment language bundle does not match the selected release")
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".deployment-", dir=target.parent)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(downloaded)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, 0o644)
                # Exclusive publication never overwrites a concurrently installed file.
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    if (
                        target.is_symlink()
                        or target.read_text(encoding="utf-8").strip() != expected
                    ):
                        raise ValueError("Deployment language bundle changed during download")
            finally:
                Path(temporary).unlink(missing_ok=True)
            return bundle
        raise missing


def tr(message_key: str, **parameters: Any) -> str:
    global _deployment_messages
    if _deployment_messages is None:
        configure_language([])
    assert _deployment_messages is not None
    message = _deployment_messages[_deployment_language][message_key]
    return re.sub(r"\{(\w+)\}", lambda match: str(parameters.get(match[1], match[0])), message)


def deployment_catalog(source: str) -> dict[str, Any]:
    """Validate the non-executable language bundle before replacing deployment tools."""
    if not source or len(source.encode("utf-8")) > 1024 * 1024:
        raise UpdateError("Invalid deployment language bundle")
    try:

        def unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        data = json.loads(source, object_pairs_hook=unique_object)
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError
        messages = data["messages"]
        if set(messages) != {"en", "de"}:
            raise ValueError

        def flatten(value: Any, prefix: str = "") -> dict[str, str]:
            if not isinstance(value, dict):
                raise ValueError
            result = {}
            for key, child in value.items():
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key):
                    raise ValueError
                name = f"{prefix}.{key}" if prefix else key
                if isinstance(child, dict):
                    result.update(flatten(child, name))
                elif isinstance(child, str) and child:
                    result[name] = child
                else:
                    raise ValueError
            return result

        en, de = (flatten(messages[language]) for language in ("en", "de"))
        if not en or en.keys() != de.keys():
            raise ValueError
        for key in en:
            if set(re.findall(r"\{(\w+)\}", en[key])) != set(re.findall(r"\{(\w+)\}", de[key])):
                raise ValueError
        return {"en": en, "de": de}
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise UpdateError("Invalid deployment language bundle") from error


def release_language_bundle(source: str) -> bool:
    """Older releases have standalone updaters and do not require a bundle."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEPLOYMENT_LANGUAGE_BUNDLE"
            for target in node.targets
        ):
            if (
                not isinstance(node.value, ast.Constant)
                or node.value.value != DEPLOYMENT_LANGUAGE_BUNDLE
            ):
                raise UpdateError("Unsupported deployment language bundle path")
            return True
    return False


def frontend_file(name: str, role: str = "main") -> bool:
    """Only public build outputs; no dotfiles, source maps or server state."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name):
        return False
    if any(part.startswith(".") or not part for part in name.split("/")):
        return False
    if "/" in name:
        return name.startswith("assets/") and Path(name).suffix in {
            ".js",
            ".css",
            ".svg",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".ico",
            ".woff",
            ".woff2",
        }
    entrypoints = (
        {"companion.html", FRONTEND_METADATA}
        if role == "companion"
        else {"index.html", "sw.js", "manifest.webmanifest", FRONTEND_METADATA}
    )
    return name in entrypoints or (Path(name).suffix in {".png", ".ico", ".svg"})


class AssetRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        url = urllib.parse.urlsplit(newurl)
        if url.scheme != "https" or url.netloc not in {
            "api.github.com",
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        }:
            raise UpdateError(tr("messages.unexpectedGitHubAssetRedirect"))
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and url.netloc != urllib.parse.urlsplit(req.full_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def download_frontend(
    repository: str, tag: str, destination: Path, token: str | None, role: str = "main"
) -> Path:
    asset_name = COMPANION_FRONTEND_ASSET if role == "companion" else FRONTEND_ASSET
    release = release_request(repository, f"/tags/{urllib.parse.quote(tag, safe='')}", token)
    if release_tag(release) != tag:
        raise UpdateError(tr("messages.githubReturnedADifferentReleaseTagThanRequested"))
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        raise UpdateError(tr("messages.githubReturnedAnInvalidReleaseAssetList"))
    matches = [a for a in assets if isinstance(a, dict) and a.get("name") == asset_name]
    if len(matches) != 1:
        raise UpdateError(
            tr(
                "messages.selectedReleaseHasNoUniquePrebuiltFrontendWaitForItsReleaseWorkflowToFinishOrUseBuildFrontendToBuildLocally"
            )
        )
    asset = matches[0]
    asset_id, size, digest = asset.get("id"), asset.get("size"), asset.get("digest")
    if (
        type(asset_id) is not int
        or asset_id <= 0
        or type(size) is not int
        or not 0 < size <= MAX_FRONTEND_DOWNLOAD
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or asset.get("state") != "uploaded"
    ):
        raise UpdateError(tr("messages.prebuiltFrontendHasMissingOrInvalidSizeSHA256Metadata"))
    headers = {"Accept": "application/octet-stream", "User-Agent": "label-server-updater"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/assets/{asset_id}", headers=headers
    )
    archive = destination / asset_name
    checksum = hashlib.sha256()
    received = 0
    try:
        opener = urllib.request.build_opener(AssetRedirectHandler())
        with opener.open(request, timeout=60) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > size:
                    raise UpdateError(tr("messages.prebuiltFrontendExceedsItsDeclaredSize"))
                checksum.update(chunk)
                output.write(chunk)
    except (OSError, urllib.error.URLError) as error:
        # Do not expose credentials, response bodies or signed redirect URLs.
        raise UpdateError(tr("messages.couldNotDownloadThePrebuiltFrontendFromGitHub")) from error
    if received != size or checksum.hexdigest() != digest.removeprefix("sha256:"):
        raise UpdateError(tr("messages.prebuiltFrontendSizeOrSHA256VerificationFailed"))
    return archive


def unpack_frontend(archive: Path, destination: Path, commit: str, role: str = "main") -> None:
    """Validate the whole archive before writing any file; never use extractall."""
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            names = [entry.filename for entry in entries]
            required = {FRONTEND_METADATA} | (
                {"companion.html"}
                if role == "companion"
                else {"index.html", "sw.js", "manifest.webmanifest"}
            )
            if (
                len(entries) > 4096
                or len(set(names)) != len(names)
                or sum(entry.file_size for entry in entries) > MAX_FRONTEND_UNPACKED
                or not required <= set(names)
                or not any(name.startswith("assets/") and name.endswith(".js") for name in names)
            ):
                raise UpdateError(tr("messages.prebuiltFrontendHasAnInvalidFileListOrSize"))
            for entry in entries:
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if (
                    not frontend_file(entry.filename, role)
                    or entry.is_dir()
                    or mode not in {0, stat.S_IFREG}
                    or entry.flag_bits & 1
                ):
                    raise UpdateError(tr("messages.prebuiltFrontendContainsAnUnsafeFile"))
            if bundle.getinfo(FRONTEND_METADATA).file_size > 4096:
                raise UpdateError(tr("messages.prebuiltFrontendBuildMetadataIsTooLarge"))
            metadata = json.loads(bundle.read(FRONTEND_METADATA))
            if (
                not isinstance(metadata, dict)
                or metadata.get("schema") != 1
                or metadata.get("commit") != commit
                or metadata.get("role", "main") != role
            ):
                raise UpdateError(
                    tr("messages.prebuiltFrontendDoesNotMatchTheSelectedSourceCommit")
                )
            destination.mkdir(mode=0o755)
            destination.chmod(0o755)
            for entry in entries:
                target = destination / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                target.chmod(0o644)
            for directory in destination.rglob("*"):
                if directory.is_dir():
                    directory.chmod(0o755)
    except (
        zipfile.BadZipFile,
        NotImplementedError,
        RuntimeError,
        UnicodeError,
        ValueError,
    ) as error:
        raise UpdateError(tr("messages.prebuiltFrontendArchiveIsInvalid")) from error


def install_frontend(staged: Path, install_dir: Path, role: str = "main") -> None:
    frontend = install_dir / "frontend"
    target = frontend / ("dist-companion" if role == "companion" else "dist")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise UpdateError(tr("messages.frontendDistMustBeADirectoryNotAFileOrSymlink"))
    with tempfile.TemporaryDirectory(prefix=".frontend-install-", dir=frontend) as temporary:
        temporary_path = Path(temporary)
        replacement, previous = temporary_path / "dist", temporary_path / "previous"
        shutil.copytree(staged, replacement)
        if target.exists():
            target.rename(previous)
        try:
            replacement.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise


def handoff_updater(args: argparse.Namespace, commit: str, tag: str) -> bool:
    """Run each release with its own updater, without switching live application code."""
    source = command(["git", "show", f"{commit}:scripts/update.py"], args.checkout, capture=True)
    if not source or len(source.encode()) > 1024 * 1024:
        raise UpdateError(tr("messages.selectedReleaseHasAnInvalidUpdater"))
    try:
        compile(source, "release-updater", "exec")
    except SyntaxError as error:
        raise UpdateError(
            tr("messages.selectedReleaseUpdaterIsNotCompatibleWithThisPython")
        ) from error
    target = Path(__file__).resolve()
    bundle_target = target.parent.parent / DEPLOYMENT_LANGUAGE_BUNDLE
    bundle_source = None
    if release_language_bundle(source):
        bundle_source = command(
            ["git", "show", f"{commit}:{DEPLOYMENT_LANGUAGE_BUNDLE}"], args.checkout, capture=True
        )
        deployment_catalog(bundle_source)
        if bundle_target.is_symlink() or bundle_target.parent.is_symlink():
            raise UpdateError(tr("messages.deploymentLanguageBundleMustNotBeASymlink"))
    if source == target.read_text().strip() and (
        bundle_source is None
        or bundle_target.is_file()
        and bundle_target.read_text().strip() == bundle_source
    ):
        return False
    descriptor, filename = tempfile.mkstemp(
        prefix=f"updater-{commit[:12]}-", suffix=".py", dir=args.backup_dir
    )
    with os.fdopen(descriptor, "w") as output:
        output.write(target.read_text())
        output.flush()
        os.fsync(output.fileno())
    previous_bundle = (
        bundle_target.read_bytes() if bundle_source is not None and bundle_target.exists() else None
    )
    if previous_bundle is not None:
        Path(filename + ".language.json").write_bytes(previous_bundle)
    # Publish atomically only after the old updater has been backed up. A failed
    # write leaves the wrapper's existing target usable.
    descriptor, replacement = tempfile.mkstemp(prefix=".update-", dir=target.parent)
    bundle_replaced = False
    bundle_replacement = None
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(source + "\n")
            output.flush()
            os.fsync(output.fileno())
        shutil.copymode(target, replacement)
        if bundle_source is not None:
            bundle_target.parent.mkdir(parents=True, exist_ok=True)
            bundle_descriptor, bundle_replacement = tempfile.mkstemp(
                prefix=".deployment-", dir=bundle_target.parent
            )
            with os.fdopen(bundle_descriptor, "w") as output:
                output.write(bundle_source + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(bundle_replacement, 0o644)
            os.replace(bundle_replacement, bundle_target)
            bundle_replaced = True
        os.replace(replacement, target)
    except BaseException:
        if bundle_replaced:
            if previous_bundle is None:
                bundle_target.unlink()
            else:
                # Restore the previous bundle before returning to the old updater.
                descriptor, restored = tempfile.mkstemp(
                    prefix=".deployment-", dir=bundle_target.parent
                )
                try:
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(previous_bundle)
                        output.flush()
                        os.fsync(output.fileno())
                    os.chmod(restored, 0o644)
                    os.replace(restored, bundle_target)
                finally:
                    Path(restored).unlink(missing_ok=True)
        raise
    finally:
        Path(replacement).unlink(missing_ok=True)
        if bundle_replacement is not None:
            Path(bundle_replacement).unlink(missing_ok=True)
    invocation = [
        *(["sudo"] if args.mode == "native" else []),
        str(
            target.parent.parent / "update.sh"
            if target.parent.name == "scripts"
            else args.checkout / "update.sh"
        ),
        *args.invocation,
        "--checkout",
        str(args.checkout),
        "--install-dir",
        str(args.install_dir),
        "--backup-dir",
        str(args.backup_dir),
        "--tag",
        tag,
        "--mode",
        args.mode,
    ]
    print(
        tr("progress.handoff", filename=filename, command=shlex.join(invocation)),
        flush=True,
    )
    return True


class UpdateError(Exception):
    pass


def environment_entries(text: str) -> Generator[tuple[str, str], None, None]:
    """Read assignments with their preceding comments without evaluating values.

    Quoted multiline values stay together, so a line inside a secret cannot be
    mistaken for another setting. Commented examples remain commented.
    """
    lines = iter(text.splitlines(keepends=True))
    pending: list[str] = []
    for line in lines:
        pending.append(line)
        match = re.match(r"^\s*(#\s*)?(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)", line)
        if not match:
            continue
        value = match[3].lstrip()
        if not match[1] and value.startswith(("'", '"')):
            quote = value[0]
            remainder = value[1:]
            escaped = False
            while True:
                closed = False
                for char in remainder:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        closed = True
                        break
                if closed:
                    break
                continuation = next(lines, None)
                if continuation is None:
                    raise UpdateError(
                        tr("messages.unterminatedQuotedEnvironmentValueConfigurationUnchanged")
                    )
                pending.append(continuation)
                remainder = continuation
        yield match[2], "".join(pending)
        pending = []


def sync_environment_files(args: argparse.Namespace) -> None:
    """Append missing example settings after rollback backups, before startup."""
    if args.no_env_update:
        return
    for name in (".env", ".env.companion"):
        target = args.install_dir / name
        example = args.checkout / f"{name}.example"
        if target.is_symlink():
            raise UpdateError(tr("progress.symlinkEnv", name=name))
        if not target.is_file() or not example.is_file():
            continue
        original = target.read_bytes()
        metadata = target.stat()
        text = original.decode("utf-8")
        keys = {key for key, _ in environment_entries(text)}
        additions = []
        for key, block in environment_entries(example.read_text()):
            if key not in keys:
                additions.append(block)
                keys.add(key)
        if not additions:
            continue
        content = text + ("\n" if text and not text.endswith("\n") else "")
        content += "\n" + "".join(additions)
        descriptor, temporary = tempfile.mkstemp(prefix=f"{name}.update-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content.encode("utf-8"))
                current = os.fstat(output.fileno())
                if (current.st_uid, current.st_gid) != (metadata.st_uid, metadata.st_gid):
                    os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
                os.fchmod(output.fileno(), stat.S_IMODE(metadata.st_mode))
                output.flush()
                os.fsync(output.fileno())
            latest = target.stat()
            identity = (
                "st_ino",
                "st_dev",
                "st_mtime_ns",
                "st_ctime_ns",
                "st_size",
                "st_mode",
                "st_uid",
                "st_gid",
            )
            if (
                target.is_symlink()
                or target.read_bytes() != original
                or any(getattr(latest, field) != getattr(metadata, field) for field in identity)
            ):
                raise UpdateError(tr("progress.envChanged", name=name))
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        print(tr("progress.envAdded", name=name, count=len(additions)), flush=True)


def confirm_operation(question: str, *, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise UpdateError(
            tr("messages.confirmationRequiresAnInteractiveTerminalUseYesForUnattendedOperation")
        )
    try:
        accepted = input(tr("progress.confirm", question=question)).strip().lower() in (
            {"y", "yes", "j", "ja"} if _deployment_language == "de" else {"y", "yes"}
        )
    except EOFError:
        accepted = False
    if not accepted:
        print(tr("messages.cancelledNoInstallationOrUpdateWasPerformed"))
    return accepted


def prompt_value(question: str, default: str = "", choices: tuple[str, ...] = ()) -> str:
    """Prompt for a missing choice; cancellation must never imply consent."""
    suffix = f" ({'/'.join(choices)})" if choices else ""
    suffix += f" [{default}]" if default else ""
    while True:
        try:
            value = input(question + suffix + ": ").strip() or default
        except (EOFError, KeyboardInterrupt):
            raise UpdateError(tr("messages.cancelledNoDeploymentChangesMade")) from None
        if value and (not choices or value in choices):
            return value
        print(
            tr("progress.choose", choices=", ".join(choices))
            if choices
            else tr("progress.required")
        )


def command(
    args: list[str],
    cwd: Path,
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
    input: str | None = None,
) -> str:
    print("+ " + shlex.join(args), flush=True)
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=capture, input=input)
    if result.returncode:
        # Captured configuration/inspection output can contain credentials.
        raise UpdateError(
            tr("progress.commandFailed", code=result.returncode, command=shlex.join(args))
        )
    return result.stdout.strip() if capture else ""


def github_repository(remote: str) -> str:
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?",
        remote,
    )
    if not match:
        raise UpdateError(tr("messages.originMustBeAGitHubHTTPSOrSSHRepositoryURL"))
    return match[1]


def release_request(repository: str, path: str, token: str | None = None) -> Any:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise UpdateError(tr("messages.repositoryMustBeOWNERREPOSITORY"))
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "label-server-updater"}
    if token := token or os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases{path}", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise UpdateError(
                tr("messages.noPublishedReleaseFoundOrRepositoryAccessIsUnavailable")
            ) from error
        raise UpdateError(tr("progress.releaseHttp", code=error.code)) from error
    except (OSError, ValueError) as error:
        raise UpdateError(tr("messages.couldNotReadGitHubReleaseInformation")) from error


def valid_tag(tag: str) -> bool:
    return bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/+\-]*", tag)
        and ".." not in tag
        and not tag.endswith((".", "/"))
        and all(
            part and not part.startswith(".") and not part.endswith(".lock")
            for part in tag.split("/")
        )
    )


def release_tag(release: Any, *, stable: bool = False) -> str:
    tag = release.get("tag_name") if isinstance(release, dict) else None
    if (
        not isinstance(tag, str)
        or not valid_tag(tag)
        or release.get("draft")
        or (stable and release.get("prerelease"))
    ):
        raise UpdateError(tr("progress.noStableTag" if stable else "progress.noTag"))
    return tag


def latest_release(repository: str, token: str | None = None) -> str:
    return release_tag(release_request(repository, "/latest", token), stable=True)


def beta_release(repository: str, token: str | None = None) -> str:
    """Newest publication across stable and prerelease releases, excluding drafts."""
    newest: tuple[datetime, bool, str] | None = None
    page = 1
    while True:
        releases = release_request(repository, f"?per_page=100&page={page}", token)
        if not isinstance(releases, list):
            raise UpdateError(tr("messages.githubDidNotReturnAReleaseList"))
        for release in releases:
            if isinstance(release, dict) and release.get("draft"):
                continue
            tag = release_tag(release)
            try:
                published = datetime.fromisoformat(release["published_at"])
                if published.utcoffset() is None:
                    raise ValueError("Missing timezone")
            except (KeyError, TypeError, ValueError) as error:
                raise UpdateError(
                    tr("messages.githubReturnedAnInvalidReleasePublicationDate")
                ) from error
            candidate = (published, not bool(release.get("prerelease")), tag)
            if newest is None or candidate > newest:
                newest = candidate
        if len(releases) < 100:
            break
        page += 1
    if newest is None:
        raise UpdateError(tr("messages.noPublishedReleaseFoundForTheBetaChannel"))
    return newest[2]


def tagged_release(repository: str, tag: str, token: str | None = None) -> str:
    if not valid_tag(tag):
        raise UpdateError(tr("messages.invalidReleaseTag"))
    selected = release_tag(
        release_request(repository, f"/tags/{urllib.parse.quote(tag, safe='')}", token)
    )
    if selected != tag:
        raise UpdateError(tr("messages.githubReturnedADifferentReleaseTagThanRequested"))
    return selected


def installation_token(args: argparse.Namespace) -> str | None:
    """Read credentials as data, never execute installation configuration."""
    args.github_token_path = None
    values: dict[str, str] = {}
    dotenv = args.install_dir / (
        ".env.companion" if getattr(args, "role", "main") == "companion" else ".env"
    )
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            match = re.match(r"\s*(?:export\s+)?(LABEL_GITHUB_TOKEN(?:_FILE)?)\s*=\s*(.*)", line)
            if match:
                try:
                    parts = shlex.split(match[2], comments=True)
                except ValueError as error:
                    raise UpdateError(tr("messages.invalidGitHubCredentialSettingInEnv")) from error
                if len(parts) > 1:
                    raise UpdateError(tr("messages.invalidGitHubCredentialSettingInEnv"))
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
            raise UpdateError(tr("messages.cannotReadTheGitHubTokenFile")) from error
        if not token:
            raise UpdateError(tr("messages.theGitHubTokenFileIsEmpty"))
    if token and not re.fullmatch(r"[A-Za-z0-9_]+", token):
        raise UpdateError(tr("messages.invalidGitHubTokenFormat"))
    return token or None


@contextmanager
def git_credentials(token: str | None) -> Generator[dict[str, str] | None, None, None]:
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


def deployment_role(directory: Path) -> str:
    """A role is installation state, never inferred from source files present in both builds."""
    marker = directory / ROLE_MARKER
    if marker.is_symlink():
        raise UpdateError(tr("messages.theInstallationRoleMarkerMustNotBeASymlink"))
    role = marker.read_text().strip() if marker.exists() else None
    if role is not None and role not in {"main", "companion"}:
        raise UpdateError(tr("messages.invalidInstallationRoleMarker"))
    main = (directory / ".env").exists()
    companion = (directory / ".env.companion").exists()
    if (main and companion) or (role == "main" and companion) or (role == "companion" and main):
        raise UpdateError(
            tr("messages.conflictingMainAndCompanionConfigurationOneServerRoleIsAllowedPerMachine")
        )
    return role or ("companion" if companion else "main")


def config_name(args: argparse.Namespace) -> str:
    return ".env.companion" if args.role == "companion" else ".env"


def compose_service(args: argparse.Namespace) -> str:
    return "companion" if args.role == "companion" else "labels"


def probe_deployment(command: list[str], directory: Path) -> str:
    """Read installed runtime state without creating files or exposing captured errors."""
    try:
        result = subprocess.run(
            command,
            cwd=directory if directory.is_dir() else None,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateError(tr("progress.inspect", command=command[0])) from error
    if result.returncode:
        raise UpdateError(tr("progress.inspect", command=command[0]))
    return result.stdout.strip()


def detect_mode(args: argparse.Namespace) -> str:
    """Use installed services/containers, never Dockerfiles shipped with every checkout."""
    detected: set[str] = set()
    unavailable: list[str] = []
    if shutil.which("systemctl"):
        try:
            properties = dict(
                line.split("=", 1)
                for line in probe_deployment(
                    [
                        "systemctl",
                        "show",
                        args.service,
                        "--property=LoadState",
                        "--property=WorkingDirectory",
                    ],
                    args.install_dir,
                ).splitlines()
                if "=" in line
            )
            working = properties.get("WorkingDirectory")
            if (
                properties.get("LoadState") == "loaded"
                and working
                and Path(working).resolve() == args.install_dir
            ):
                detected.add("native")
        except UpdateError:
            unavailable.append("systemd")
    if shutil.which("docker") and args.checkout.is_dir():
        command = [
            "docker",
            "ps",
            "--all",
            "--filter",
            f"label=com.docker.compose.project.working_dir={args.checkout}",
            "--filter",
            f"label=com.docker.compose.service={compose_service(args)}",
            "--format",
            "{{.ID}}",
        ]
        if args.project_name:
            command += ["--filter", f"label=com.docker.compose.project={args.project_name}"]
        try:
            if probe_deployment(command, args.checkout):
                detected.add("docker")
        except UpdateError:
            unavailable.append("Docker")
    if len(detected) == 1:
        return detected.pop()
    reason = tr("progress.ambiguous" if detected else "progress.notFound")
    if unavailable:
        reason = tr("progress.unavailable", reason=reason, tools=", ".join(unavailable))
    raise UpdateError(tr("progress.modeAdvice", reason=reason))


def options(argv: list[str] | None = None) -> argparse.Namespace:
    invocation = list(sys.argv[1:] if argv is None else argv)
    language = configure_language(invocation)
    parser = argparse.ArgumentParser(description=tr("update.description"))
    parser.add_argument(
        "--language", choices=("en", "de"), default=language, help=tr("common.language")
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=("auto", "native", "docker"),
        help=tr("messages.detectTheInstalledRuntimeDefaultOrExplicitlySelectNativeDocker"),
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=tr("messages.acceptedForCompatibilityUpdatesAlreadyRunWithoutPrompting"),
    )
    parser.add_argument(
        "--channel",
        choices=("stable", "beta"),
        default="stable",
        help=tr("messages.releaseChannelStableDefaultOrNewestPublicationIncludingPrereleases"),
    )
    parser.add_argument("--tag", help=tr("messages.publishedReleaseTagToInstallOverridesChannel"))
    parser.add_argument(
        "--no-env-update",
        action="store_true",
        help=tr("messages.doNotCompareExistingEnvironmentFilesWithReleaseExamplesOrAddSettings"),
    )
    frontend = parser.add_mutually_exclusive_group()
    frontend.add_argument(
        "--prebuilt-frontend",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    frontend.add_argument(
        "--build-frontend",
        action="store_true",
        help=tr("messages.buildTheNativeFrontendLocallyInsteadOfDownloadingReleaseAssets"),
    )
    parser.add_argument(
        "--checkout",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=tr("messages.gitCheckoutAMissingDirectoryIsClonedAutomatically"),
    )
    parser.add_argument(
        "--install-dir",
        type=Path,
        help=tr("messages.nativeApplicationDirectoryIfSeparateFromTheSourceCheckout"),
    )
    parser.add_argument("--repository", help=tr("messages.githubOWNERREPOSITORYDefaultsToOrigin"))
    parser.add_argument(
        "--github-token-file", type=Path, help=tr("messages.fileContainingARawGitHubToken")
    )
    parser.add_argument(
        "--backup-dir", type=Path, help=tr("messages.backupParentOutsideApplicationDataPaths")
    )
    parser.add_argument("--service", default="labels.service")
    parser.add_argument(
        "--compose-file",
        action="append",
        default=[],
        help=tr("messages.composeFileRepeatForUSBLocalOverrides"),
    )
    parser.add_argument(
        "--project-name", help=tr("messages.existingComposeProjectNameIfExplicitlySet")
    )
    parser.add_argument("--health-url", help=tr("messages.overrideTheServiceSLocalHealthURL"))
    parser.add_argument("--health-timeout", type=float, default=60)
    parser.add_argument(
        "--check",
        action="store_true",
        help=tr("messages.showTheReleaseAndPlanWithoutChangingAnything"),
    )
    args = parser.parse_args(invocation)
    args.invocation = invocation
    if args.tag is not None and not valid_tag(args.tag):
        parser.error(tr("messages.tagMustBeAValidReleaseTagName"))
    args.checkout = args.checkout.resolve()
    args.install_dir = (args.install_dir or args.checkout).resolve()
    args.role = deployment_role(args.install_dir)
    args.health_url_explicit = args.health_url is not None
    args.health_url = (
        args.health_url
        or f"http://127.0.0.1:{8001 if args.role == 'companion' else 8000}/api/health"
    )
    if args.role == "companion" and not args.compose_file:
        args.compose_file = ["docker-compose.companion.yml"]
    args.backup_dir = (
        args.backup_dir or args.install_dir.parent / f"{args.install_dir.name}-backups"
    ).resolve()
    if args.install_dir != args.checkout and (
        args.install_dir.is_relative_to(args.checkout)
        or args.checkout.is_relative_to(args.install_dir)
    ):
        parser.error(tr("messages.separateSourceAndInstallationDirectoriesMustNotBeNested"))
    if args.health_timeout <= 0:
        parser.error(tr("messages.healthTimeoutMustBePositive"))
    if not args.service or args.service.startswith("-"):
        parser.error(tr("messages.invalidServiceName"))
    args.mode_detected = args.mode == "auto"
    if args.mode_detected:
        args.mode = detect_mode(args)
    if args.mode == "docker" and args.install_dir != args.checkout:
        parser.error(tr("messages.installDirIsForNativeDeploymentsComposeRunsFromCheckout"))
    if args.mode == "docker" and args.prebuilt_frontend:
        parser.error(tr("messages.prebuiltFrontendIsForNativeDeploymentsOnly"))
    args.prebuilt_frontend = args.mode == "native" and not args.build_frontend
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
        raise UpdateError(tr("messages.nativeUpdatesMustRunAsRootSudoToManageSystemdAndOwnership"))
    python = args.install_dir / ".venv/bin/python"
    if (args.install_dir / ".venv").is_symlink():
        raise UpdateError(tr("messages.automaticRollbackRequiresALocalVenvDirectoryNotASymlink"))
    if not python.is_file():
        raise UpdateError(
            tr("messages.existingNativeInstallationNeedsVenvBinPythonThisIsAnUpdaterNotAnInstaller")
        )
    unit = command(
        ["systemctl", "show", args.service, "--property=WorkingDirectory", "--value"],
        args.install_dir,
        capture=True,
    )
    if not unit or Path(unit).resolve() != args.install_dir:
        raise UpdateError(tr("messages.theSystemdWorkingDirectoryMustMatchInstallDir"))
    executable = command(
        ["systemctl", "show", args.service, "--property=ExecStart", "--value"],
        args.install_dir,
        capture=True,
    )
    expected_entrypoint = "-m companion" if args.role == "companion" else "app.main:create_app"
    if expected_entrypoint not in executable:
        raise UpdateError(tr("messages.theSystemdServiceDoesNotMatchTheDetectedServerRole"))
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
    configuration_file = config_name(args)
    expected = str(args.install_dir / configuration_file)
    if files and files not in (f"{expected} (ignore_errors=no)", f"{expected} (ignore_errors=yes)"):
        raise UpdateError(
            tr(
                "messages.customSystemdEnvironmentFilesAreUnsupportedUseTheInstallationSRoleSpecificConfiguration"
            )
        )
    if (args.install_dir / configuration_file).is_file():
        values = json.loads(
            command(
                [
                    str(python),
                    "-c",
                    f"import json; from dotenv import dotenv_values; print(json.dumps(dotenv_values({configuration_file!r}, interpolate=False)))",
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
        "kind=u.get_backend_name(); assert kind in ('sqlite','mariadb'); "
        "assert u.database not in (None, ':memory:'); "
        "d=getattr(s,'state_directory',Path(u.database).resolve().parent); "
        "assert kind != 'sqlite' or (Path(u.database).resolve().is_file() and d == Path(u.database).resolve().parent), 'SQLite database and assets must share a directory'; "
        "assert s.frontend_dist.resolve() == Path('frontend/dist').resolve(), 'Custom frontend path unsupported'; "
        "print(json.dumps({'data': str(d), 'database_kind': kind, "
        "'lock': str(getattr(s,'worker_lock_path',Path(u.database).resolve().with_suffix('.worker.lock')))}))"
    )
    if args.role == "companion":
        code = (
            "import json; from pathlib import Path; from companion.config import Settings; "
            "s=Settings(); d=s.data_dir.resolve(); "
            "assert (d/'journal.db').is_file(), 'Companion database is missing'; "
            "print(json.dumps({'data': str(d), 'lock': str(d/'station.lock'), "
            "'host': s.host, 'port': s.port}))"
        )
    configuration = json.loads(
        command([str(python), "-c", code], args.install_dir, capture=True, env=env)
    )
    data = Path(configuration["data"])
    args.database_lock = Path(configuration["lock"])
    args.database_kind = configuration.get("database_kind", "sqlite")
    if args.role == "companion" and not args.health_url_explicit:
        host: str = configuration["host"]
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
        host = f"[{host}]" if ":" in host else host
        args.health_url = f"http://{host}:{configuration['port']}/api/health"
    if not data.is_dir():
        raise UpdateError(tr("messages.configuredDataDirectoryIsMissing"))
    return data, user, env


def docker_configuration(args: argparse.Namespace) -> dict[str, Any]:
    identifiers = compose(
        args, "ps", "--all", "--quiet", compose_service(args), capture=True
    ).splitlines()
    if len(identifiers) != 1:
        raise UpdateError(
            tr("messages.expectedOneExistingLabelsContainerCheckComposeFilesProjectName")
        )
    container = json.loads(
        command(["docker", "inspect", identifiers[0]], args.checkout, capture=True)
    )[0]
    environment = dict(entry.split("=", 1) for entry in container["Config"]["Env"] if "=" in entry)
    url = environment.get("LABEL_DATABASE_URL", "sqlite:///./data/labels.db")
    if args.role == "companion":
        url = "sqlite:///" + str(
            Path(environment.get("LABEL_COMPANION_DATA_DIR", "data/companion")) / "journal.db"
        )
    if not url.startswith("sqlite:///") or "?" in url:
        raise UpdateError(
            tr(
                "messages.automaticDockerUpdatesRequireSQLiteMariaDBUpdatesCurrentlyUseTheNativeUpdaterDoNotReplaceTheImageWithoutACoord"
            )
        )
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
        raise UpdateError(tr("messages.databaseAssetsMustBeInAPersistentDockerVolumeOrBindMount"))
    mount = max(candidates, key=lambda item: len(item["Destination"]))
    if mount["Type"] not in ("volume", "bind"):
        raise UpdateError(tr("messages.unsupportedDockerDataMount"))
    if any(
        other is not mount and Path(other["Destination"]).is_relative_to(Path(mount["Destination"]))
        for other in container["Mounts"]
    ):
        raise UpdateError(
            tr("messages.nestedDataMountsNeedASeparateBackupStrategyRefusingAnIncompleteBackup")
        )
    return {
        "image": container["Image"],
        "mount": mount,
        "container_image": container["Config"]["Image"],
        "project": container["Config"]["Labels"].get("com.docker.compose.project"),
        "compose": json.loads(compose(args, "config", "--format", "json", capture=True)),
        "data_relative": database.parent.relative_to(Path(mount["Destination"])).as_posix(),
    }


@contextmanager
def backup_progress(label: str, target: Path, interval: float = 10) -> Generator[None, None, None]:
    """Report slow compression without exposing archived filenames or contents."""
    started = time.monotonic()
    finished = Event()
    print(tr("progress.backupStart", label=label), flush=True)

    def report() -> None:
        while not finished.wait(interval):
            try:
                size = tr(
                    "progress.backupSize", size=f"{target.stat().st_size / (1024 * 1024):.1f}"
                )
            except OSError:
                size = ""
            print(
                tr(
                    "progress.backupProgress",
                    label=label,
                    seconds=f"{time.monotonic() - started:.0f}",
                    size=size,
                ),
                flush=True,
            )

    reporter = Thread(target=report, name="backup-progress", daemon=True)
    reporter.start()
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        finished.set()
        reporter.join()
        print(
            tr(
                "progress.backupComplete" if succeeded else "progress.backupInterrupted",
                label=label,
                seconds=f"{time.monotonic() - started:.0f}",
            ),
            flush=True,
        )


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
        raise UpdateError(tr("messages.dockerBackupPathsMustNotContainCommas"))
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


def remove_path(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def restore_archive(
    archive: Path, target: Path, member: str | None = None, preserve: tuple[str, ...] = ()
) -> None:
    """Restore a local backup exactly, keeping protected runtime paths/inodes."""
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=archive.parent) as temporary:
        staged = Path(temporary)
        with tarfile.open(archive) as bundle:
            entries = bundle.getmembers()
            links = {PurePosixPath(entry.name).as_posix() for entry in entries if entry.issym()}
            for entry in entries:
                entry_path = PurePosixPath(entry.name)
                if (
                    entry_path.is_absolute()
                    or ".." in entry_path.parts
                    or not (entry.isfile() or entry.isdir() or entry.issym() or entry.islnk())
                    or any(parent.as_posix() in links for parent in entry_path.parents)
                ):
                    raise ValueError("Unsafe recovery archive entry")
                if entry.islnk():
                    linked = PurePosixPath(entry.linkname)
                    if (
                        linked.is_absolute()
                        or ".." in linked.parts
                        or linked.as_posix() in links
                        or any(parent.as_posix() in links for parent in linked.parents)
                    ):
                        raise ValueError("Unsafe recovery archive link")
            # Backups are locally generated in a restricted directory. Keep
            # absolute interpreter symlinks and original ownership/modes.
            bundle.extractall(staged, filter="fully_trusted")
        source = staged / member if member else staged
        if not source.is_dir() or source.is_symlink():
            raise ValueError("Recovery archive has no expected root directory")

        def protected(relative: str) -> bool:
            return any(relative == name or relative.startswith(name + "/") for name in preserve)

        def prune(path: Path, relative: str) -> None:
            if protected(relative):
                return
            if (
                any(name.startswith(relative + "/") for name in preserve)
                and path.is_dir()
                and not path.is_symlink()
            ):
                for child in path.iterdir():
                    prune(child, relative + "/" + child.name)
            else:
                remove_path(path)

        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise ValueError("Recovery target must be a real directory")
        target.mkdir(parents=True, exist_ok=True)
        for path in target.iterdir():
            prune(path, path.name)

        def copy(path: Path, destination: Path, relative: str) -> None:
            if protected(relative):
                return
            if path.is_dir() and not path.is_symlink():
                destination.mkdir(exist_ok=True)
                for child in path.iterdir():
                    copy(child, destination / child.name, relative + "/" + child.name)
                shutil.copystat(path, destination, follow_symlinks=False)
            else:
                remove_path(destination)
                shutil.copy2(path, destination, follow_symlinks=False)
            if os.geteuid() == 0:
                info = path.lstat()
                os.chown(destination, info.st_uid, info.st_gid, follow_symlinks=False)

        for path in source.iterdir():
            copy(path, target / path.name, path.name)
        if member:
            shutil.copystat(source, target)
            if os.geteuid() == 0:
                info = source.stat()
                os.chown(target, info.st_uid, info.st_gid)


# Keep the helper source in memory: restoring the checkout can replace the
# updater file on disk before Docker's data restoration runs.
DOCKER_RESTORE_SCRIPT = (
    "import os, shutil, tarfile, tempfile\nfrom pathlib import Path, PurePosixPath\n"
    + inspect.getsource(remove_path)
    + "\n"
    + inspect.getsource(restore_archive)
    + "\nrestore_archive(Path('/update-backup/data.tar.gz'), Path('/update-data'), 'data')\n"
)


def docker_data_command(
    args: argparse.Namespace, config: dict[str, Any], code: str, backup: Path | None = None
) -> None:
    mount = config["mount"]
    source = mount["Name"] if mount["Type"] == "volume" else mount["Source"]
    if "," in source or (backup and "," in str(backup)):
        raise UpdateError(tr("messages.dockerRecoveryPathsMustNotContainCommas"))
    mounts = ["--mount", f"type={mount['Type']},source={source},target=/update-data"]
    if backup:
        mounts += ["--mount", f"type=bind,source={backup},target=/update-backup"]
    command(
        [
            "docker",
            "run",
            "--rm",
            "--interactive",
            "--network",
            "none",
            "--user",
            "0:0",
            *mounts,
            "--entrypoint",
            "python",
            config["image"],
            "-",
        ],
        args.checkout,
        input=code,
    )


def validation_marker(
    args: argparse.Namespace,
    data: Path | None,
    docker: dict[str, Any] | None,
    enabled: bool | None,
) -> None:
    if data:
        marker = data / UPDATE_MARKER
        if enabled is None:
            if marker.exists() or marker.is_symlink():
                raise UpdateError(tr("messages.anUnfinishedUpdateNeedsRecoveryBeforeUpdatingAgain"))
        elif enabled:
            marker.touch(mode=0o644, exist_ok=False)
        else:
            marker.unlink()
    elif docker:
        path = str(Path("/update-data") / docker.get("data_relative", ".") / UPDATE_MARKER)
        if enabled is None:
            code = (
                f"from pathlib import Path\np = Path({path!r})\n"
                "if p.exists() or p.is_symlink():\n"
                "    raise RuntimeError('An unfinished update needs recovery before updating again')\n"
            )
        else:
            action = "touch(mode=0o644, exist_ok=False)" if enabled else "unlink()"
            code = f"from pathlib import Path\nPath({path!r}).{action}\n"
        docker_data_command(args, docker, code)


def require_validation_protocol(source: str) -> None:
    """Do not start a release that could print before rollback is committed."""
    for statement in ast.parse(source).body:
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "UPDATE_VALIDATION_PROTOCOL"
                for target in statement.targets
            )
            and isinstance(statement.value, ast.Constant)
            and statement.value.value == 1
        ):
            return
    raise UpdateError(tr("messages.selectedReleaseDoesNotSupportSafeUpdateValidation"))


def running(args: argparse.Namespace) -> bool:
    if args.mode == "native":
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", args.service], cwd=args.install_dir
        )
        if result.returncode not in (0, 3):
            raise UpdateError(tr("messages.couldNotDetermineTheSystemdServiceState"))
        return result.returncode == 0
    return bool(compose(args, "ps", "--quiet", compose_service(args), capture=True))


def stop_application(args: argparse.Namespace) -> None:
    if args.mode == "native":
        command(["systemctl", "stop", args.service], args.install_dir)
        if running(args):
            raise UpdateError(tr("messages.applicationRemainedRunningAfterStopRecoveryIsUnsafe"))
    else:
        if not args.project_name:
            raise UpdateError(tr("messages.cannotSafelyStopDockerWithoutItsExistingProjectName"))
        query = [
            "docker",
            "ps",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={args.project_name}",
            "--filter",
            f"label=com.docker.compose.service={compose_service(args)}",
        ]
        identifiers = command(query, args.checkout, capture=True).splitlines()
        if identifiers:
            command(["docker", "stop", *identifiers], args.checkout)
        if command(query, args.checkout, capture=True):
            raise UpdateError(tr("messages.applicationRemainedRunningAfterStopRecoveryIsUnsafe"))


def restore_checkout(args: argparse.Namespace, metadata: dict[str, Any]) -> None:
    if not metadata["previous_commit"]:
        return  # A newly created source checkout has no previous application state.
    command(["git", "switch", "--detach", "--force", metadata["previous_commit"]], args.checkout)
    if metadata["previous_release"]:
        command(
            ["git", "update-ref", "refs/heads/release", metadata["previous_release"]], args.checkout
        )
    else:
        command(["git", "update-ref", "-d", "refs/heads/release"], args.checkout)
    if metadata["previous_branch"]:
        command(["git", "switch", metadata["previous_branch"]], args.checkout)


def restore_deployment(
    args: argparse.Namespace,
    metadata: dict[str, Any],
    backup: Path,
    data: Path | None,
    docker: dict[str, Any] | None,
) -> argparse.Namespace:
    restore_checkout(args, metadata)
    preserved = [".git", ".venv", "frontend/node_modules"]
    mount_data = (
        Path(docker["mount"]["Source"]) if docker and docker["mount"]["Type"] == "bind" else data
    )
    if mount_data and mount_data.is_relative_to(args.install_dir):
        preserved.append(mount_data.relative_to(args.install_dir).as_posix())
    restore_archive(backup / "source.tar.gz", args.install_dir, preserve=tuple(preserved))
    if data:
        lock = getattr(args, "database_lock", None)
        preserved_locks = (lock.relative_to(data).as_posix(),) if lock else ()
        restore_archive(backup / "data.tar.gz", data, "data", preserved_locks)
        restore_archive(backup / "venv.tar.gz", args.install_dir / ".venv", ".venv")
    elif docker:
        docker_data_command(args, docker, DOCKER_RESTORE_SCRIPT, backup)
        for item in metadata.get("compose_files", []):
            shutil.copy2(item["backup"], item["original"])
        configuration = json.loads(json.dumps(docker["compose"]))
        service = configuration["services"][compose_service(args)]
        service.pop("build", None)
        service["image"] = docker["image"]
        service["pull_policy"] = "never"

        def literal_values(value: Any) -> Any:
            # `compose config` has already interpolated these values, including
            # credentials. Prevent a second interpolation in the recovery file.
            if isinstance(value, str):
                return value.replace("$", "$$")
            if isinstance(value, list):
                return [literal_values(item) for item in value]
            if isinstance(value, dict):
                return {key: literal_values(item) for key, item in value.items()}
            return value

        pinned = backup / "rollback-compose.json"
        pinned.write_text(json.dumps(literal_values(configuration)))
        original_tag = docker["container_image"]
        if not original_tag.startswith("sha256:") and "@" not in original_tag:
            command(["docker", "tag", docker["image"], original_tag], args.checkout)
        args = argparse.Namespace(**vars(args))
        args.compose_file = [str(pinned)]
    return args


def start_application(args: argparse.Namespace) -> None:
    if args.mode == "native":
        command(["systemctl", "daemon-reload"], args.install_dir)
        command(["systemctl", "start", args.service], args.install_dir)
    else:
        compose(
            args,
            "up",
            "--detach",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            compose_service(args),
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
    raise UpdateError(tr("progress.healthTimeout", seconds=f"{timeout:g}", url=url))


@contextmanager
def update_lock(path: Path) -> Generator[None, None, None]:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise UpdateError(tr("messages.anotherUpdateIsRunningForThisInstallation")) from error
        yield


class RemoteDatabase:
    """Keep credentials inside the service environment and a dedicated DB lock process."""

    def __init__(self, args: argparse.Namespace, env: dict[str, str] | None):
        self.process = subprocess.Popen(
            [str(args.install_dir / ".venv/bin/python"), "-m", "scripts.database_maintenance"],
            cwd=args.install_dir,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            result = self.response()
            if not result.get("ready") or not isinstance(result.get("owner"), int):
                raise UpdateError(tr("messages.mariadbMaintenanceDidNotAcquireOwnership"))
            self.owner = str(result["owner"])
        except BaseException:
            self.close()
            raise

    def response(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            raise UpdateError(
                tr("messages.mariadbMaintenanceStoppedNoAutomaticActivationIsAllowed")
            )
        result = json.loads(line)
        if not isinstance(result, dict) or result.get("error"):
            raise UpdateError(
                tr("messages.mariadbMaintenanceFailedCheckAccessSchemaAndAvailableBackupSpace")
            )
        return result

    def perform(self, action: str, path: Path) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({"action": action, "path": str(path)}) + "\n")
        self.process.stdin.flush()
        if self.response().get("ok") is not True:
            raise UpdateError(tr("messages.mariadbMaintenanceDidNotComplete"))

    def close(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()


def update(args: argparse.Namespace) -> None:
    checkout = args.checkout
    existing = (checkout / ".git").exists()
    if checkout.exists() and not existing:
        raise UpdateError(
            tr(
                "messages.checkoutMustBeAGitCheckoutOrANewDirectoryForACopiedNativeInstallationUseCheckoutOptLabelsSourceInstallDirOptLa"
            )
        )
    repository = args.repository or DEFAULT_REPOSITORY
    changes = ""
    handoff_paths: set[str] = set()
    if existing:
        remote = command(["git", "remote", "get-url", "origin"], checkout, capture=True)
        actual = github_repository(remote)
        if args.repository and repository.lower() != actual.lower():
            raise UpdateError(tr("messages.repositoryDoesNotMatchOrigin"))
        repository = actual
        changes = command(
            ["git", "status", "--porcelain", "--untracked-files=all"], checkout, capture=True
        )
        # Handoff changes must match the executing tools and the selected release.
        handoff_paths = {
            line.strip()[3:] if line.strip().startswith("?? ") else line.strip()[2:]
            for line in changes.splitlines()
        }
        refreshed_updater = (
            bool(changes)
            and all(
                line.strip()
                in {
                    "M scripts/update.py",
                    f"M {DEPLOYMENT_LANGUAGE_BUNDLE}",
                    f"?? {DEPLOYMENT_LANGUAGE_BUNDLE}",
                }
                for line in changes.splitlines()
            )
            and (checkout / "scripts/update.py").read_bytes() == Path(__file__).read_bytes()
            and (
                DEPLOYMENT_LANGUAGE_BUNDLE not in handoff_paths
                or (
                    not (checkout / DEPLOYMENT_LANGUAGE_BUNDLE).is_symlink()
                    and (checkout / DEPLOYMENT_LANGUAGE_BUNDLE).read_bytes()
                    == (
                        Path(__file__).resolve().parents[1] / DEPLOYMENT_LANGUAGE_BUNDLE
                    ).read_bytes()
                )
            )
            and not command(["git", "diff", "--cached", "--name-only"], checkout, capture=True)
        )
        if changes and not refreshed_updater:
            raise UpdateError(tr("messages.checkoutHasLocalChangesCommitOrMoveThemBeforeUpdating"))
        if command(["git", "rev-parse", "--show-toplevel"], checkout, capture=True) != str(
            checkout
        ):
            raise UpdateError(tr("messages.checkoutMustBeTheRepositoryRoot"))
    token = installation_token(args)
    if args.tag:
        tag = tagged_release(repository, args.tag, token)
    elif args.channel == "beta":
        tag = beta_release(repository, token)
    else:
        tag = latest_release(repository, token) if token else latest_release(repository)
    for protected in (checkout, args.install_dir):
        if args.backup_dir.is_relative_to(protected):
            raise UpdateError(tr("messages.backupDirectoryMustBeOutsideTheCheckoutAndInstallation"))
    print(
        tr(
            "progress.selection",
            repository=repository,
            tag=tag,
            role=args.role,
            selection=tr("progress.explicitTag") if args.tag else args.channel,
            mode=args.mode,
            detection=tr("progress.detected" if args.mode_detected else "progress.override"),
            checkout=checkout,
            installation=args.install_dir,
            backups=args.backup_dir,
        ),
        flush=True,
    )
    print(
        tr(
            "progress.updatePlan",
            frontend=tr("progress.downloadFrontend") if args.prebuilt_frontend else "",
            install=tr(
                "progress.installFrontend" if args.prebuilt_frontend else "progress.buildFrontend"
            ),
            database=tr("progress.migrate" if args.role == "main" else "progress.preserveJournal"),
        )
    )
    if args.check:
        return
    required = ["git", "systemctl", "runuser"] if args.mode == "native" else ["git", "docker"]
    if args.mode == "native" and not args.prebuilt_frontend:
        required.append("npm")
    if args.mode == "native" and args.install_dir != checkout:
        required.append("rsync")
    for executable in required:
        if not shutil.which(executable):
            raise UpdateError(tr("progress.missingCommand", command=executable))
    if args.mode == "native":
        data, user, env = native_configuration(args)
        if args.install_dir.is_relative_to(data) or checkout.is_relative_to(data):
            raise UpdateError(
                tr("messages.useADedicatedDataDirectorySeparateFromTheApplicationSourceDirectories")
            )
        if args.backup_dir.is_relative_to(data):
            raise UpdateError(tr("messages.backupDirectoryMustBeOutsideConfiguredData"))
        docker = None
    else:
        data, user, env = None, "", None
        docker = docker_configuration(args) if existing else None
        if docker is None:
            raise UpdateError(
                tr("messages.dockerUpdatesRequireAnExistingCheckoutAndComposeContainer")
            )
        # Pin the old project even if a later release changes the top-level Compose name.
        args.project_name = docker["project"] or args.project_name
    print(
        tr(
            "progress.target",
            target=args.service
            if args.mode == "native"
            else tr("progress.composeProject", project=args.project_name),
        )
    )
    args.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = args.install_dir.parent / f".{args.install_dir.name}.update.lock"
    with update_lock(lock_path), ExitStack() as runtime_locks, ExitStack() as database_locks:
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
        if (
            existing
            and changes
            and any(
                command(["git", "show", f"{commit}:{path}"], checkout, capture=True)
                != (checkout / path).read_text().strip()
                for path in handoff_paths
            )
        ):
            raise UpdateError(tr("messages.locallyChangedUpdaterDoesNotMatchTheSelectedRelease"))
        # Refuse a release that tries to overwrite deployment state or use submodules.
        files = command(
            ["git", "ls-tree", "-r", "--name-only", commit], checkout, capture=True
        ).splitlines()
        required_files = {
            "scripts/update.py",
            "pyproject.toml",
            "requirements.lock",
            "companion/requirements.txt" if args.role == "companion" else "alembic.ini",
            "frontend/package.json",
            "frontend/package-lock.json",
        }
        if getattr(args, "database_kind", "sqlite") == "mariadb":
            required_files.update(
                {
                    "scripts/database_maintenance.py",
                    "app/database_lock.py",
                    "migrations/mariadb_baseline.sql",
                }
            )
        if args.mode == "docker":
            required_files.add("Dockerfile.companion" if args.role == "companion" else "Dockerfile")
        if missing := required_files - set(files):
            raise UpdateError(tr("progress.missingFiles", files=", ".join(sorted(missing))))
        protected = [
            ".env",
            ".env.companion",
            ROLE_MARKER,
            "data",
            ".venv",
            "frontend/node_modules",
        ]
        if args.github_token_path:
            for directory in (checkout, args.install_dir):
                if args.github_token_path.is_relative_to(directory):
                    relative_token = args.github_token_path.relative_to(directory).as_posix()
                    if any(relative_token.startswith(path + "/") for path in files):
                        raise UpdateError(
                            tr("messages.releaseWouldOverwriteTheGitHubTokenFileSDirectory")
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
                tr("messages.releaseContainsDeploymentStateOrSubmodulesRefusingAutomaticUpdate")
            )
        if data and data.is_relative_to(args.install_dir):
            relative_data = data.relative_to(args.install_dir).as_posix()
            if any(path == relative_data or path.startswith(relative_data + "/") for path in files):
                raise UpdateError(
                    tr("messages.releaseContainsFilesInsideTheConfiguredDataDirectory")
                )
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
                    tr(
                        "messages.theReleaseBranchDivergedFromTheSelectedReleaseRefusingToDiscardCommits"
                    )
                )
        old_commit = (
            command(["git", "rev-parse", "HEAD"], checkout, capture=True) if existing else None
        )
        old_branch = (
            subprocess.run(
                ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                cwd=checkout,
                capture_output=True,
                text=True,
            )
            if existing
            else None
        )
        if not existing:
            # This is a new, separate source checkout, not the running installation.
            # Materialize it so a handoff can resume with a clean working tree.
            command(["git", "switch", "--detach", commit], checkout)
        if handoff_updater(args, commit, tag):
            return
        require_validation_protocol(
            command(
                [
                    "git",
                    "show",
                    f"{commit}:{'companion/web.py' if args.role == 'companion' else 'app/main.py'}",
                ],
                checkout,
                capture=True,
            )
        )
        validation_marker(args, data, docker, None)
        staged_frontend = None
        if args.prebuilt_frontend:
            temporary = Path(
                runtime_locks.enter_context(tempfile.TemporaryDirectory(prefix="label-frontend-"))
            )
            print(
                tr("messages.downloadingAndVerifyingTheReleaseFrontendBeforeShutdown"), flush=True
            )
            archive = (
                download_frontend(repository, tag, temporary, token, args.role)
                if args.role == "companion"
                else download_frontend(repository, tag, temporary, token)
            )
            staged_frontend = temporary / "dist"
            unpack_frontend(archive, staged_frontend, commit, args.role)
        backup = args.backup_dir / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        )
        backup.mkdir(mode=0o700)
        print(tr("progress.backupPath", backup=backup), flush=True)
        metadata = {
            "repository": repository,
            "release": tag,
            "commit": commit,
            "previous_commit": old_commit,
            "previous_branch": old_branch.stdout.strip()
            if old_branch and old_branch.returncode == 0
            else None,
            "previous_release": branch.stdout.strip() if branch.returncode == 0 else None,
            "mode": args.mode,
            "role": args.role,
            "install_dir": str(args.install_dir),
            "data_dir": str(data) if data else None,
            "docker": docker,
            "status": "preparing",
        }

        def record(status: str) -> None:
            metadata["status"] = status
            (backup / "update.json").write_text(json.dumps(metadata, indent=2) + "\n")

        was_running = running(args)
        metadata["was_running"] = was_running
        record("preparing")
        changed = False
        database_locked = False
        activated = False
        remote_database = None
        try:
            stop_application(args)
            record("stopped")
            print(tr("messages.serviceStoppedPreparingRollbackBackups"), flush=True)
            if args.mode == "native" and getattr(args, "database_lock", None):
                if not args.database_lock.exists():
                    # A freshly migrated installation may not have started yet.
                    # Create its lock as the service user, not the root updater.
                    command(
                        [
                            "runuser",
                            "-u",
                            user,
                            "--",
                            str(args.install_dir / ".venv/bin/python"),
                            "-c",
                            "from pathlib import Path; import sys; Path(sys.argv[1]).touch(mode=0o600)",
                            str(args.database_lock),
                        ],
                        args.install_dir,
                        env=env,
                    )
                try:
                    database_locks.enter_context(update_lock(args.database_lock))
                    database_locked = True
                except UpdateError as error:
                    raise UpdateError(
                        tr(
                            "messages.anotherProcessStillOwnsTheDatabaseNoBackupOrMigrationWasAttempted"
                        )
                    ) from error
            archive_data = (
                Path(docker["mount"]["Source"])
                if docker and docker["mount"]["Type"] == "bind"
                else data
            )
            if getattr(args, "database_kind", "sqlite") == "mariadb":
                remote_database = RemoteDatabase(args, env)
                with backup_progress(tr("progress.databaseBackup"), backup / "database.json.gz"):
                    remote_database.perform("backup", backup / "database.json.gz")
            with backup_progress(tr("progress.applicationBackup"), backup / "source.tar.gz"):
                archive_source(args.install_dir, backup / "source.tar.gz", archive_data)
            if (args.install_dir / config_name(args)).is_file():
                shutil.copy2(args.install_dir / config_name(args), backup / "environment.env")
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
                with backup_progress(tr("progress.dataBackup"), backup / "data.tar.gz"):
                    with tarfile.open(backup / "data.tar.gz", "w:gz") as bundle:
                        bundle.add(data, arcname="data")
                with backup_progress(tr("progress.pythonBackup"), backup / "venv.tar.gz"):
                    with tarfile.open(backup / "venv.tar.gz", "w:gz") as bundle:
                        bundle.add(args.install_dir / ".venv", arcname=".venv")
            elif docker:
                with backup_progress(tr("progress.dataBackup"), backup / "data.tar.gz"):
                    docker_backup(args, docker, backup)
            record("backed_up")
            changed = True  # Even a failed Git switch may have touched application files.
            if existing and changes:
                # The refreshed script is verified above and included in the source
                # backup. Restore only this path so Git can switch releases normally.
                for path in handoff_paths:
                    if f"?? {path}" in changes:
                        (checkout / path).unlink()
                    else:
                        command(["git", "restore", "--worktree", "--", path], checkout)
            command(["git", "switch", "--force-create", "release", commit], checkout)
            sync_environment_files(args)
            if args.mode == "native":
                if args.install_dir != checkout:
                    excludes = [
                        "--exclude=/.git",
                        "--exclude=/.env",
                        "--exclude=/.env.companion",
                        f"--exclude=/{ROLE_MARKER}",
                        "--exclude=/.venv",
                        "--exclude=/data",
                        "--exclude=/frontend/node_modules",
                        "--exclude=/frontend/dist",
                        "--exclude=/frontend/dist-companion",
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
                    [
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "-c",
                        "requirements.lock",
                        *(
                            ["-r", "companion/requirements.txt"]
                            if args.role == "companion"
                            else ["."]
                        ),
                    ],
                    args.install_dir,
                    env=env,
                )
                if staged_frontend is not None:
                    install_frontend(staged_frontend, args.install_dir, args.role)
                else:
                    command(["npm", "ci", "--prefix", "frontend"], args.install_dir)
                    command(
                        [
                            "npm",
                            "run",
                            "build:companion" if args.role == "companion" else "build",
                            "--prefix",
                            "frontend",
                        ],
                        args.install_dir,
                    )
                if args.role == "main":
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
                        env={
                            **(env or {}),
                            "LABEL_DATABASE_MAINTENANCE_OWNER": remote_database.owner,
                        }
                        if remote_database
                        else env,
                    )
                validation_marker(args, data, docker, True)
                database_locks.close()
                database_locked = False
                if remote_database:
                    remote_database.close()
                    remote_database = None
                start_application(args)
            else:
                compose(args, "build", "--pull", compose_service(args))
                if args.role == "main":
                    migration = ["run", "--rm", "--no-deps"]
                    if (args.install_dir / ".env").is_file():
                        migration += [
                            "--volume",
                            f"{args.install_dir / '.env'}:/srv/labels/.env:ro",
                        ]
                    record("migrating")
                    compose(args, *migration, "labels", "alembic", "upgrade", "head")
                validation_marker(args, data, docker, True)
                start_application(args)
            wait_healthy(args.health_url, args.health_timeout)
            if not running(args):
                raise UpdateError(tr("messages.applicationIsNotRunningAfterStartup"))
            record("complete")
            # This is the commit point: once activation is attempted, a remote
            # Docker error cannot prove that printing has not already resumed.
            activated = True
            validation_marker(args, data, docker, False)
        except BaseException:
            try:
                record("rolling_back")
            except OSError:
                print(
                    tr("messages.couldNotSaveFailureStatusAttemptingRecoveryAnyway"),
                    file=sys.stderr,
                )
            recovery_args = args
            try:
                stop_application(args)
                if activated:
                    raise UpdateError(
                        tr(
                            "messages.activationOutcomeIsUncertainAutomaticDataRestoreCouldReplayPrints"
                        )
                    )
                if changed:
                    if data and getattr(args, "database_lock", None) and not database_locked:
                        database_locks.enter_context(update_lock(args.database_lock))
                    recovery_args = restore_deployment(args, metadata, backup, data, docker)
                    if getattr(args, "database_kind", "sqlite") == "mariadb":
                        remote_database = remote_database or RemoteDatabase(args, env)
                        remote_database.perform("restore", backup / "database.json.gz")
                if remote_database:
                    remote_database.close()
                    remote_database = None
                database_locks.close()
                if was_running:
                    start_application(recovery_args)
                    wait_healthy(args.health_url, args.health_timeout)
                    if not running(recovery_args):
                        raise UpdateError(tr("messages.previousApplicationDidNotRemainRunning"))
            except BaseException as recovery_error:
                if remote_database:
                    try:
                        remote_database.close()
                    except Exception:
                        print(
                            tr(
                                "messages.databaseMaintenanceDidNotShutDownCleanlyInspectItBeforeRecovery"
                            ),
                            file=sys.stderr,
                        )
                    remote_database = None
                try:
                    stop_application(recovery_args)
                except BaseException:
                    print(
                        tr("messages.couldNotConfirmShutdownCheckTheServiceStateBeforeRecovery"),
                        file=sys.stderr,
                    )
                status = "rollback_failed"
                reason = (
                    str(recovery_error)
                    if isinstance(recovery_error, UpdateError)
                    else type(recovery_error).__name__
                )
                print(
                    tr("progress.rollbackFailed", reason=reason, backup=backup),
                    file=sys.stderr,
                )
            else:
                status = "rolled_back"
                print(
                    tr(
                        "progress.restoredRunning" if was_running else "progress.restoredStopped",
                        backup=backup,
                    ),
                    file=sys.stderr,
                )
            try:
                record(status)
            except OSError:
                print(tr("messages.couldNotSaveRecoveryStatusTheBackupIsRetained"), file=sys.stderr)
            raise
        print(tr("progress.updated", tag=tag, commit=commit[:12], backup=backup))


def main(argv: list[str] | None = None) -> int:
    try:
        update(options(argv))
    except (UpdateError, OSError, ValueError) as error:
        # Bootstrap failures cannot be rendered through an unavailable catalog.
        print(
            tr("progress.aborted", error=error) if _deployment_messages is not None else str(error),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print(tr("messages.updateInterrupted"), file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
