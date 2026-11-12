"""The root launcher preserves updater arguments, relative paths and exit status."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("status", [0, 7])
@pytest.mark.parametrize("launcher", ["update", "install"])
def test_wrapper_forwards_arguments_without_shell_expansion(tmp_path, status, launcher):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    wrapper = root / f"{launcher}.sh"
    shutil.copyfile(Path(__file__).resolve().parents[1] / f"{launcher}.sh", wrapper)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python3"
    python.write_text('#!/bin/sh\npwd\nprintf "%s\\n" "$@"\nexit ' + str(status) + "\n")
    python.chmod(0o755)
    arguments = ["--env-file", "relative path/.env", "$(touch unexpected)", "", "--check"]
    result = subprocess.run(
        ["sh", str(wrapper), *arguments],
        cwd=tmp_path,
        env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == status
    assert result.stdout.splitlines() == [
        str(tmp_path),
        str(root / f"scripts/{launcher}.py"),
        *arguments,
    ]
    assert not (tmp_path / "unexpected").exists()
