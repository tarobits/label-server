"""Interactive choices retain explicit overrides and unattended safeguards."""

import pytest

from scripts import install, update


def replies(monkeypatch, answers):
    iterator = iter(answers)
    prompts = []
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: True)

    def reply(prompt):
        prompts.append(prompt)
        return next(iterator)

    monkeypatch.setattr("builtins.input", reply)
    return prompts


def test_installer_wizard_defaults_are_local_and_require_confirmation(monkeypatch):
    prompts = replies(monkeypatch, [""] * 9)
    args = install.options([])
    assert args.role == "main" and args.host == "127.0.0.1" and args.port == 8000
    assert str(args.install_dir) == "/opt/labels"
    assert args.public_url == "http://localhost:8000" and args.ref is None
    assert not args.yes and not args.skip_packages and not args.no_start
    assert len(prompts) == 9


def test_companion_wizard_uses_private_config_without_prompting_for_secrets(monkeypatch, tmp_path):
    private = tmp_path / "companion.env"
    prompts = replies(
        monkeypatch,
        ["companion", "/opt/station", str(private), "specific", "v2.0.0", "existing", "no"],
    )
    args = install.options([])
    assert args.companion_config == private and args.role == "companion"
    assert args.companion_overrides == {} and args.ref == "v2.0.0"
    assert args.no_start and args.skip_packages
    assert not any("API key" in prompt for prompt in prompts)


def test_wizard_retries_invalid_choice_and_port(monkeypatch):
    replies(monkeypatch, ["bad role", "main", "", "", "", "22", "abc", "8080", "", "", "", ""])
    assert install.options([]).port == 8080


@pytest.mark.parametrize("argv", [["--check"], ["--yes"], ["--host=127.0.0.2"]])
def test_installer_options_skip_wizard(monkeypatch, argv):
    replies(monkeypatch, [])
    args = install.options(argv)
    assert args.host == ("127.0.0.2" if argv[0].startswith("--host") else "127.0.0.1")


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_prompt_cancellation_never_continues(monkeypatch, interruption):
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: True)

    def cancel(_):
        raise interruption()

    monkeypatch.setattr("builtins.input", cancel)
    with pytest.raises(update.UpdateError, match="Cancelled"):
        install.options([])


@pytest.mark.parametrize("terminal", [False, True])
def test_updater_without_options_uses_defaults_without_prompts(monkeypatch, terminal):
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: terminal)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Updater must never prompt"))
    monkeypatch.setattr(update, "detect_mode", lambda _: "native")
    args = update.options([])
    assert args.channel == "stable" and args.prebuilt_frontend
    assert args.mode_detected and args.mode == "native"
    assert not args.no_env_update and not args.check
    assert args.invocation == []


@pytest.mark.parametrize("extra", [["--yes"], ["--check"], ["--channel=beta", "--build-frontend"]])
def test_updater_explicit_and_unattended_choices_do_not_prompt(monkeypatch, extra):
    replies(monkeypatch, [])
    args = update.options(["--mode=native", *extra])
    assert args.prebuilt_frontend == ("--build-frontend" not in extra)


def test_ambiguous_runtime_requires_explicit_option_even_in_terminal(monkeypatch, tmp_path):
    replies(monkeypatch, [])

    def ambiguous(_):
        raise update.UpdateError("Both runtimes match")

    monkeypatch.setattr(update, "detect_mode", ambiguous)
    with pytest.raises(update.UpdateError, match="Both runtimes"):
        update.options(["--checkout", str(tmp_path), "--channel=stable"])
    assert update.options(["--checkout", str(tmp_path), "--mode=docker"]).mode == "docker"


def test_noninteractive_missing_runtime_does_not_guess(monkeypatch, tmp_path):
    monkeypatch.setattr(update.sys.stdin, "isatty", lambda: False)

    def ambiguous(_):
        raise update.UpdateError("Both runtimes match")

    monkeypatch.setattr(update, "detect_mode", ambiguous)
    with pytest.raises(update.UpdateError, match="Both runtimes"):
        update.options(["--checkout", str(tmp_path), "--yes"])
