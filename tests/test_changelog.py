"""Account-wide release visits, independent of browser storage and sessions."""

import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth import auth_client as auth_fixture
from test_auth import invite, login, register_member, setup_admin

from app import __version__
from app.models import User

auth_client = auth_fixture
NEXT_VERSION = f"{__version__.split('.')[0]}.{int(__version__.split('.')[1]) + 1}.0"


def test_every_release_links_to_version_tags():
    source = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text()
    versions = re.findall(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", source, re.MULTILINE)
    references = dict(re.findall(r"^\[([^\]]+)\]:\s+(\S+)\s*$", source, re.MULTILINE))
    # Release references always use version tags, including tags not yet created.
    # Branch names and commit hashes must not become release references.
    ref = r"v[0-9]+\.[0-9]+\.[0-9]+"
    target = re.compile(
        rf"https://github\.com/tarobits/label-server/(?:compare/{ref}\.\.\.{ref}|tree/{ref})"
    )
    assert versions, "The changelog must contain released versions"
    for version in versions:
        assert version in references, f"Missing changelog reference for {version}"
    for name, url in references.items():
        assert target.fullmatch(url), f"Changelog reference {name} must use version tags"


def test_visit_requires_session_csrf_and_same_origin(auth_client, tmp_path):
    client = auth_client
    assert client.post("/api/auth/changelog").status_code == 401
    setup_admin(client, tmp_path)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/auth/changelog").status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.post("/api/auth/changelog", headers={"Origin": "https://other.test"}).status_code
        == 403
    )
    first = client.post("/api/auth/changelog")
    assert first.status_code == 200
    assert first.json() == {"current_version": __version__, "previous_version": None}
    assert first.headers["cache-control"] == "private, no-store"
    assert client.post("/api/auth/changelog").json()["previous_version"] == __version__


def test_skipped_versions_are_claimed_once_across_sessions_and_accounts(
    auth_client, tmp_path, monkeypatch
):
    client = auth_client
    setup_admin(client, tmp_path)
    client.post("/api/auth/changelog")
    with client.app.state.factory.begin() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        user.last_seen_version = "0.1.0"
    monkeypatch.setattr("app.auth_api.__version__", NEXT_VERSION)
    # Reuse the running application's database without restarting its lifespan.
    with closing(TestClient(client.app)) as other:
        login(other)
        result = other.post("/api/auth/changelog").json()
        assert result == {"current_version": NEXT_VERSION, "previous_version": "0.1.0"}
        assert client.post("/api/auth/changelog").json()["previous_version"] == NEXT_VERSION
    code = invite(client)
    register_member(client, code)
    assert client.post("/api/auth/changelog").json()["previous_version"] is None
    assert client.post("/api/auth/changelog").json()["previous_version"] == NEXT_VERSION


def test_simultaneous_tabs_claim_history_once_and_downgrades_do_not_rewind(
    auth_client, tmp_path, monkeypatch
):
    client = auth_client
    setup_admin(client, tmp_path)
    client.post("/api/auth/changelog")
    monkeypatch.setattr("app.auth_api.__version__", NEXT_VERSION)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: client.post("/api/auth/changelog").json(), range(8)))
    assert [result["previous_version"] for result in results].count(__version__) == 1
    assert [result["previous_version"] for result in results].count(NEXT_VERSION) == 7
    monkeypatch.setattr("app.auth_api.__version__", "0.2.0")
    assert client.post("/api/auth/changelog").json()["previous_version"] == NEXT_VERSION
    monkeypatch.setattr("app.auth_api.__version__", NEXT_VERSION)
    assert client.post("/api/auth/changelog").json()["previous_version"] == NEXT_VERSION
