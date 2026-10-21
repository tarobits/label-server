"""Release comparison, caching and private repository credentials without network IO."""

import io
import json
import time
import tomllib
from pathlib import Path
from threading import Event

import pytest
from test_access_security import accounts as account_fixture

from app import __version__
from app.config import Settings
from app.releases import ReleaseChecker, fetch_release, stable_version

accounts = account_fixture


def complete(checker):
    deadline = time.monotonic() + 2
    while True:
        result = checker.status()
        if result["check_status"] != "checking":
            return result
        assert time.monotonic() < deadline
        time.sleep(0.005)


def test_version_numbers_match_release_metadata():
    root = Path(__file__).resolve().parents[1]
    assert tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"] == __version__
    assert json.loads((root / "frontend/package.json").read_text())["version"] == __version__
    assert json.loads((root / "frontend/package-lock.json").read_text())["version"] == __version__


@pytest.mark.parametrize(
    "tag,newer", [("v0.1.1", True), ("v0.10.0", True), ("0.1.0", False), ("v0.0.9", False)]
)
def test_only_newer_versions_notify_and_success_is_cached(tag, newer):
    calls = []
    checker = ReleaseChecker(Settings(), lambda: calls.append(True) or tag)
    result = complete(checker)
    assert result["current_version"] == __version__
    assert result["update_available"] is newer
    assert result["release_url"].endswith(f"/releases/tag/{tag}")
    assert checker.status() == result
    assert calls == [True]


@pytest.mark.parametrize("tag", ["v0.1.1-rc1", "v1", "javascript:alert(1)", "v01.0.0"])
def test_unstable_or_malformed_versions_are_rejected(tag):
    with pytest.raises(ValueError):
        stable_version(tag)


def test_failures_are_cached_and_do_not_leak_credentials():
    calls = []

    def failed():
        calls.append(True)
        raise RuntimeError("secret-token")

    checker = ReleaseChecker(Settings(), failed)
    result = complete(checker)
    assert result["check_status"] == "unavailable"
    assert not result["update_available"]
    assert "secret-token" not in json.dumps(result)
    assert checker.status() == result
    assert calls == [True]
    checker.next_check = 0
    checker.fetch = lambda: "v0.1.1"
    assert complete(checker)["update_available"]


def test_concurrent_status_calls_return_immediately_and_share_one_check():
    started, finish = Event(), Event()

    def fetch():
        started.set()
        assert finish.wait(2)
        return "v0.1.1"

    checker = ReleaseChecker(Settings(), fetch)
    try:
        assert checker.status()["current_version"] == __version__
        assert started.wait(1)
        for _ in range(20):
            assert checker.status()["check_status"] == "checking"
    finally:
        finish.set()
    assert complete(checker)["update_available"]


def test_disabled_check_never_contacts_github():
    checker = ReleaseChecker(Settings(check_for_updates=False), lambda: pytest.fail("No network"))
    assert checker.status()["check_status"] == "disabled"


@pytest.mark.parametrize("use_file", [False, True])
def test_private_release_request_uses_server_token(monkeypatch, tmp_path, use_file):
    token = "github_pat_testonly"
    config = {"github_token": token}
    if use_file:
        path = tmp_path / "token"
        path.write_text(token + "\n")
        config = {"github_token_file": path}

    def open_request(request, timeout):
        assert request.get_header("Authorization") == f"Bearer {token}"
        assert timeout == 5
        assert "github_pat" not in request.full_url
        return io.BytesIO(json.dumps({"tag_name": "v0.1.1"}).encode())

    monkeypatch.setattr("app.releases.urlopen", open_request)
    assert fetch_release(Settings(**config)) == "v0.1.1"


def test_version_endpoint_requires_signin_and_returns_no_token(accounts):
    admin, _, _ = accounts
    app = admin.app
    app.state.releases.enabled = False
    response = admin.get("/api/version")
    assert response.status_code == 200
    assert response.json()["current_version"] == __version__
    assert "token" not in response.text
    from fastapi.testclient import TestClient

    anonymous = TestClient(app)
    try:
        assert anonymous.get("/api/version").status_code == 401
    finally:
        anonymous.close()
