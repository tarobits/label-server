"""Localized deployment tools preserve safe handoff and unattended operation."""

import ast
import json
from pathlib import Path

import pytest

from scripts import install, update


@pytest.fixture(autouse=True)
def isolated_language(monkeypatch):
    monkeypatch.setattr(update, "_deployment_language", "en")
    monkeypatch.setattr(update, "_deployment_messages", None)
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "environment, override, language",
    [
        ({"LANG": "de_DE.UTF-8"}, [], "de"),
        ({"LANG": "de_DE.UTF-8", "LC_MESSAGES": "en_GB.UTF-8"}, [], "en"),
        ({"LANG": "en_US.UTF-8", "LC_ALL": "de_AT.UTF-8"}, [], "de"),
        ({"LC_ALL": "fr_FR.UTF-8"}, [], "en"),
        ({"LC_ALL": "de_DE.UTF-8"}, ["--language", "en"], "en"),
        ({"LC_ALL": "C"}, ["--language=de"], "de"),
    ],
)
def test_locale_precedence_and_override_do_not_prompt(monkeypatch, environment, override, language):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Updater must not prompt"))
    args = update.options(["--mode", "native", *override])
    assert args.language == language
    assert args.prebuilt_frontend
    text = update.tr("progress.aborted", error="{secret}")
    assert text == (
        "Update abgebrochen: {secret}" if language == "de" else "Update aborted: {secret}"
    )
    assert "{secret}" in text  # Parameter contents must not be interpreted as placeholders.


def test_installer_help_and_errors_use_override_without_starting_wizard(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Help must not prompt"))
    with pytest.raises(SystemExit) as stopped:
        install.options(["--language", "de", "--help"])
    assert stopped.value.code == 0
    assert "Installation ohne Rückfrage bestätigen" in capsys.readouterr().out
    with pytest.raises(SystemExit) as stopped:
        install.options(["--language", "de", "--role", "companion"])
    assert stopped.value.code == 2
    assert "erfordert --companion-config" in capsys.readouterr().err
    assert install.options(["--language", "en", "--check"]).check


def test_deployment_catalog_keys_and_parameters_match_actual_calls():
    root = Path(__file__).resolve().parents[1]
    catalogs = update.deployment_catalog((root / update.DEPLOYMENT_LANGUAGE_BUNDLE).read_text())
    for filename in ("update.py", "install.py"):
        for node in ast.walk(ast.parse((root / "scripts" / filename).read_text())):
            if not isinstance(node, ast.Call) or ast.unparse(node.func) not in {"tr", "update.tr"}:
                continue
            if isinstance(node.args[0], ast.Constant):
                for language in ("en", "de"):
                    assert node.args[0].value in catalogs[language], (filename, node.lineno)


@pytest.mark.parametrize(
    "bundle",
    [
        '{"schema":1,"schema":1,"messages":{"en":{"name":"X"},"de":{"name":"Y"}}}',
        '{"schema":1,"messages":{"en":{"name":"{value}"},"de":{"name":"{other}"}}}',
        '{"schema":1,"messages":{"en":{"name":"X"},"de":{"name":2}}}',
    ],
)
def test_invalid_catalog_does_not_poison_next_valid_load(bundle):
    with pytest.raises(update.UpdateError, match="Invalid deployment language bundle"):
        update.deployment_catalog(bundle)
    assert update.configure_language(["--language=de"]) == "de"
    assert update.tr("progress.required") == "Ein Wert ist erforderlich."


@pytest.mark.parametrize("failure", [None, "invalid", "replace", "missingLocale"])
def test_bundle_handoff_restores_old_pair_on_failure_and_allows_retry(
    tmp_path, monkeypatch, failure
):
    update.configure_language([])
    root = tmp_path / "checkout"
    target = root / "scripts/update.py"
    target.parent.mkdir(parents=True)
    target.write_text("# old updater\n")
    target.chmod(0o755)
    bundle = root / update.DEPLOYMENT_LANGUAGE_BUNDLE
    bundle.parent.mkdir()
    original = json.dumps({"schema": 1, "messages": {"en": {"name": "Old"}, "de": {"name": "Alt"}}})
    replacement = json.dumps(
        {"schema": 1, "messages": {"en": {"name": "New"}, "de": {"name": "Neu"}}}
    )
    bundle.write_text(original)
    (root / "lang/en.json").write_text("application catalog unchanged")
    backup = tmp_path / "backup"
    backup.mkdir()
    args = update.options(
        ["--mode", "native", "--checkout", str(root), "--backup-dir", str(backup)]
    )
    monkeypatch.setattr(update, "__file__", str(target))
    source = f'DEPLOYMENT_LANGUAGE_BUNDLE = "{update.DEPLOYMENT_LANGUAGE_BUNDLE}"\n# new updater'
    selected_bundle = replacement

    def command(arguments, *args, **kwargs):
        return (
            selected_bundle if arguments[-1].endswith(update.DEPLOYMENT_LANGUAGE_BUNDLE) else source
        )

    monkeypatch.setattr(update, "command", command)
    if failure:
        with monkeypatch.context() as patch:
            if failure == "invalid":
                selected_bundle = "not JSON"
            elif failure == "missingLocale":
                selected_bundle = json.dumps({"schema": 1, "messages": {"en": {"name": "New"}}})
            else:
                replace = update.os.replace

                def fail_script(source, destination):
                    if Path(destination) == target:
                        raise OSError("simulated disk error")
                    return replace(source, destination)

                patch.setattr(update.os, "replace", fail_script)
            with pytest.raises((update.UpdateError, OSError)):
                update.handoff_updater(args, "a" * 40, "v2.0.0")
        assert target.read_text() == "# old updater\n"
        assert bundle.read_text() == original
        assert not list(root.rglob(".deployment-*"))
        assert not list(root.rglob(".update-*"))
    selected_bundle = replacement
    assert update.handoff_updater(args, "a" * 40, "v2.0.0")
    assert target.read_text().strip() == source
    assert bundle.read_text().strip() == replacement
    assert (root / "lang/en.json").read_text() == "application catalog unchanged"
    assert any(path.read_text() == original for path in backup.glob("*.language.json"))
    assert not update.handoff_updater(args, "a" * 40, "v2.0.0")
