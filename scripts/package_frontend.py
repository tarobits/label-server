"""Package a clean release build: python -m scripts.package_frontend --tag vVERSION."""

import argparse
import json
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .update import FRONTEND_ASSET, FRONTEND_METADATA, frontend_file, unpack_frontend, valid_tag


def package_frontend(root: Path, output: Path, tag: str) -> Path:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    if not valid_tag(tag):
        raise ValueError("Invalid release tag")
    commit = git("rev-parse", "HEAD")
    if git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}") != commit:
        raise ValueError("Checkout does not match the release tag")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Package from a clean release checkout")
    version = json.loads((root / "frontend/package.json").read_text())["version"]
    if tag != f"v{version}":
        raise ValueError("Release tag does not match the frontend version")
    if list((root / "frontend").glob(".env*")):
        raise ValueError("Release builds must not contain frontend environment files")
    dist = root / "frontend/dist"
    if dist.is_symlink() or not dist.is_dir():
        raise ValueError("Build frontend/dist before packaging")
    files = []
    for file in sorted(dist.rglob("*")):
        if file.is_symlink():
            raise ValueError("Symlinks are not allowed in release builds")
        if file.is_dir():
            continue
        name = file.relative_to(dist).as_posix()
        if not file.is_file() or not frontend_file(name) or name == FRONTEND_METADATA:
            raise ValueError("Unexpected file in frontend build")
        files.append((name, file))
    output.mkdir(parents=True, exist_ok=True)
    archive = output / FRONTEND_ASSET
    metadata = json.dumps({"schema": 1, "commit": commit, "version": version}) + "\n"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, contents in [
            (FRONTEND_METADATA, metadata.encode()),
            *((name, file.read_bytes()) for name, file in files),
        ]:
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, contents)
    # Apply exactly the validation used by the updater before publishing.
    with tempfile.TemporaryDirectory() as temporary:
        unpack_frontend(archive, Path(temporary) / "dist", commit)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/release"))
    args = parser.parse_args()
    print(package_frontend(Path.cwd(), args.output.resolve(), args.tag))


if __name__ == "__main__":
    main()
