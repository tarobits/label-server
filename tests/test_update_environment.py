"""Environment defaults must not overwrite local choices or expose secrets."""

from argparse import Namespace

import pytest
from test_update import deployment as deployment
from test_update import git
from test_update import (
    test_updates_exact_tag_preserves_main_and_backups_and_rolls_back_on_failure as run_update,
)

from scripts import update


def arguments(tmp_path, **overrides):
    return Namespace(install_dir=tmp_path, checkout=tmp_path, no_env_update=False, **overrides)


def test_missing_options_keep_comments_values_permissions_and_are_idempotent(tmp_path, capsys):
    original = 'export EXISTING="custom # value"\nEMPTY=\n# OPTIONAL=disabled\nSECRET="line one\nNEW=inside a secret\nline three"'
    target = tmp_path / ".env"
    target.write_text(original)
    target.chmod(0o640)
    (tmp_path / ".env.example").write_text(
        "EXISTING=default\nEMPTY=default\n# OPTIONAL=placeholder\n"
        "# First explanation.\n# Second explanation.\nNEW=42\n"
        "# An alternative, not a second assignment.\n# NEW=99\n"
        "# Optional credentials.\n# TOKEN=example-placeholder\n"
    )
    (tmp_path / ".env.companion").write_text("LOCAL=keep\n")
    (tmp_path / ".env.companion.example").write_text("# Device default.\nDEVICE=false\n")
    update.sync_environment_files(arguments(tmp_path))
    result = target.read_text()
    assert result.startswith(original + "\n")
    assert "# First explanation.\n# Second explanation.\nNEW=42\n" in result
    assert "# Optional credentials.\n# TOKEN=example-placeholder\n" in result
    assert "NEW=99" not in result and "EXISTING=default" not in result
    assert "OPTIONAL=placeholder" not in result and "EMPTY=default" not in result
    assert target.stat().st_mode & 0o777 == 0o640
    assert "# Device default.\nDEVICE=false\n" in (tmp_path / ".env.companion").read_text()
    before = target.stat().st_ino
    update.sync_environment_files(arguments(tmp_path))
    assert target.read_text() == result and target.stat().st_ino == before
    assert "inside a secret" not in capsys.readouterr().out


def test_skip_does_not_read_examples_and_missing_configs_are_not_created(tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text("NEW=true\n")
    update.sync_environment_files(arguments(tmp_path))
    assert not (tmp_path / ".env").exists()
    args = arguments(tmp_path)
    args.no_env_update = True
    with monkeypatch.context() as patch:
        patch.setattr(
            update.Path, "read_text", lambda *a, **kw: pytest.fail("Must not compare examples")
        )
        patch.setattr(
            update.Path,
            "read_bytes",
            lambda *a, **kw: pytest.fail("Must not compare configuration"),
        )
        update.sync_environment_files(args)
    assert update.options(["--mode", "native", "--no-env-update"]).no_env_update


@pytest.mark.parametrize("failure", ["replace", "malformed", "concurrent", "symlink"])
def test_environment_failure_keeps_config_and_allows_retry(tmp_path, monkeypatch, failure):
    target = tmp_path / ".env"
    original = "EXISTING=keep\n"
    target.write_text(original)
    example = tmp_path / ".env.example"
    example.write_text("NEW=true\n")
    with monkeypatch.context() as patch:
        if failure == "replace":

            def fail_replace(*args):
                raise OSError("disk failure")

            patch.setattr(update.os, "replace", fail_replace)
        elif failure == "malformed":
            example.write_text('NEW="unterminated\n')
        elif failure == "concurrent":
            fsync = update.os.fsync

            def edit_while_writing(fd):
                target.write_text("EXISTING=new user choice\n")
                fsync(fd)

            patch.setattr(update.os, "fsync", edit_while_writing)
        else:
            target.rename(tmp_path / "outside.env")
            target.symlink_to(tmp_path / "outside.env")
        with pytest.raises((update.UpdateError, OSError)):
            update.sync_environment_files(arguments(tmp_path))
    expected = "EXISTING=new user choice\n" if failure == "concurrent" else original
    assert target.read_text() == expected
    assert not list(tmp_path.glob(".env.update-*"))
    if failure == "symlink":
        target.unlink()
        (tmp_path / "outside.env").rename(target)
    example.write_text("NEW=true\n")
    update.sync_environment_files(arguments(tmp_path))
    assert target.read_text().startswith(expected)
    assert "NEW=true" in target.read_text()


@pytest.mark.parametrize("mode", ["native", "docker"])
@pytest.mark.parametrize("failure", [None, "health"])
def test_env_sync_participates_in_deployment_rollback(deployment, monkeypatch, mode, failure):
    root, data, previous, newest = deployment
    original = (root / ".env").read_bytes()
    git(root, "switch", "--detach", newest)
    (root / ".env.example").write_text("# New budget.\nNEW_BUDGET=2\n")
    git(root, "add", ".env.example")
    git(root, "commit", "-m", "Add configuration default")
    newest = git(root, "rev-parse", "HEAD")
    git(root, "tag", "--force", "v2.0.0")
    git(root, "switch", "main")
    run_update((root, data, previous, newest), monkeypatch, mode, failure)
    if failure:
        assert (root / ".env").read_bytes() == original
    else:
        assert (root / ".env").read_bytes().startswith(original)
        assert "# New budget.\nNEW_BUDGET=2\n" in (root / ".env").read_text()
