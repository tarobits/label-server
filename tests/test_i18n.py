"""Shared catalogs and authenticated, account-scoped language preferences."""

from types import SimpleNamespace

import pytest
from test_auth import invite, login, register_member, setup_admin

from app.i18n import Message, catalog, negotiate, notice_text, render, user_language

pytest_plugins = ["test_auth"]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("de-DE,de;q=0.9,en;q=0.8", "de"),
        ("fr,en-US;q=0.8,de;q=0.9", "de"),
        ("de;q=0,en;q=0.5", "en"),
        ("de;q=nan,en;q=1", "en"),
        ("fr,es", "en"),
        ("", "en"),
    ],
)
def test_language_negotiation(header, expected):
    assert negotiate(header) == expected


def test_catalogs_share_nested_keys_and_english_fallback():
    assert catalog("en").keys() == catalog("de").keys()
    assert render("account.language", "en") == "Language"
    assert render("account.language", "de") == "Sprache"
    assert render("missing.key", "de") == "missing.key"


def test_named_parameters_plural_forms_and_user_content_are_safe():
    assert render("app.copyCount", "en", count=1) == "1 copy"
    assert render("app.copyCount", "de", count=2) == "2 Kopien"
    assert (
        render("app.printersConnected", "de", connected=1, total=3) == "1 von 3 Druckern verbunden"
    )
    assert (
        render("app.printersConnected", "de", connected="{total}", total=3)
        == "{total} von 3 Druckern verbunden"
    )


def test_account_and_notification_language_does_not_translate_user_content():
    assert user_language(SimpleNamespace(language="de", browser_language="en")) == "de"
    assert user_language(SimpleNamespace(language="browser", browser_language="de")) == "de"
    value = Message("account.language")
    notice = SimpleNamespace(title=str(value), context={"i18n": {"title": value.descriptor()}})
    assert notice_text(notice, "title", "de") == "Sprache"
    legacy = SimpleNamespace(title="Language", context={})
    assert notice_text(legacy, "title", "de") == "Language"


def test_language_preference_requires_session_csrf_and_origin(auth_client, tmp_path):
    client = auth_client
    body = {"language": "de", "browser_language": "en"}
    assert client.put("/api/auth/language", json=body).status_code == 401
    setup_admin(client, tmp_path)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.put("/api/auth/language", json=body).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.put(
            "/api/auth/language", json=body, headers={"Origin": "https://other.example"}
        ).status_code
        == 403
    )
    assert client.put("/api/auth/language", json={**body, "language": "../de"}).status_code == 422
    assert client.get("/api/auth/session").json()["user"]["language"] == "browser"
    response = client.put("/api/auth/language", json=body)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert login(client)["user"]["language"] == "de"


def test_language_preference_is_account_scoped(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    code = invite(client)
    assert (
        client.put(
            "/api/auth/language", json={"language": "de", "browser_language": "de"}
        ).status_code
        == 200
    )
    member = register_member(client, code)
    assert member["user"]["language"] == "browser"
    assert (
        client.put(
            "/api/auth/language", json={"language": "en", "browser_language": "de"}
        ).status_code
        == 200
    )
    assert login(client)["user"]["language"] == "de"
    assert login(client, "member")["user"]["language"] == "en"
