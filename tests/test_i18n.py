"""Shared catalogs and authenticated, account-scoped language preferences."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx
import pytest
from test_auth import invite, login, register_member, setup_admin

from app.i18n import JoinedMessages, Message, catalog, negotiate, notice_text, render, user_language

pytest_plugins = ["test_auth"]


def test_composed_notice_survives_storage_and_keeps_user_content_literal():
    name = "{count} · @:account.language"
    message = Message(
        "notificationMessages.tapeNeeded",
        profile="{destinations}",
        destinations=JoinedMessages(
            [
                Message("notificationMessages.queuedAt", count=3, name=name),
                Message("notificationMessages.queuedAt", count=5, name="Other"),
            ]
        ),
    )
    notice = SimpleNamespace(
        message=str(message),
        context=json.loads(
            json.dumps(
                {
                    "i18n": {"message": message.descriptor()},
                }
            )
        ),
    )
    german = notice_text(notice, "message", "de")
    assert name in german and "{destinations}" in german
    assert "3" in german and "5" in german and "Other" in german
    assert german != str(message)
    assert notice_text(notice, "message", "en") == str(message)
    # A historical plain string or user-provided descriptor-shaped value is not executable.
    notice.context = {}
    assert notice_text(notice, "message", "de") == str(message)
    content = {"key": "notificationMessages.tapeSwapTitle"}
    assert str(content) in render(
        "notificationMessages.tapeNeeded", "de", profile=content, destinations=""
    )


def test_permission_catalog_translates_labels_but_preserves_ids(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    english = client.get("/api/admin/permissions", headers={"Accept-Language": "en"})
    german = client.get("/api/admin/permissions", headers={"Accept-Language": "de"})
    assert english.status_code == german.status_code == 200
    assert [item["id"] for item in english.json()] == [item["id"] for item in german.json()]
    assert (
        next(item["label"] for item in german.json() if item["id"] == "usage.edit_accounts")
        == "Verbrauchskonten bearbeiten"
    )


def test_sensitive_validation_translates_without_echoing_input_and_recovers(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    secret = "must-not-be-echoed"
    response = client.put(
        "/api/auth/language",
        json={"language": secret, "browser_language": "en"},
        headers={"Accept-Language": "de"},
    )
    assert response.status_code == 422
    assert secret not in response.text
    issue = response.json()["detail"][0]
    assert set(issue) == {"type", "loc", "msg"}
    assert issue["msg"].startswith("Erwarteter Wert:")
    assert (
        client.put(
            "/api/auth/language", json={"language": "de", "browser_language": "en"}
        ).status_code
        == 200
    )


def test_server_translation_references_exist_in_both_catalogs():
    root = Path(__file__).resolve().parents[1]
    for directory in ("app", "companion"):
        for file in (root / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(file.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"Message", "render"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and "." in node.args[0].value
                ):
                    for language in ("en", "de"):
                        assert node.args[0].value in catalog(language), (
                            file,
                            node.lineno,
                            language,
                        )


def test_authentication_http_errors_do_not_reintroduce_literal_messages():
    directory = Path(__file__).resolve().parents[1] / "app" / "authn"
    for file in directory.glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "HTTPException"
            ):
                continue
            detail = next((item.value for item in node.keywords if item.arg == "detail"), None)
            if detail is None and len(node.args) > 1:
                detail = node.args[1]
            assert not isinstance(detail, (ast.Constant, ast.JoinedStr)), (file, node.lineno)


@pytest.mark.parametrize(
    "source",
    [
        "app/printing/request_notifications.py",
        "app/printing/batch_reviews.py",
        "app/printing/retry_api.py",
        "app/printing/cartridge_quote_api.py",
    ],
)
def test_migrated_notification_producer_requires_localized_messages(source):
    file = Path(__file__).resolve().parents[1] / source
    calls = [
        node
        for node in ast.walk(ast.parse(file.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "enqueue"
    ]
    assert calls
    for call in calls:
        for value in call.args[1:3]:
            assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            assert value.func.id == "Message", (file, value.lineno)


@pytest.mark.parametrize(
    "source",
    [
        "app/accounts/billing.py",
        "app/printing/retry_api.py",
        "app/printing/cartridge_quote_api.py",
        "app/printing/batch_reviews.py",
    ],
)
def test_migrated_errors_cannot_bypass_localization(source):
    file = Path(__file__).resolve().parents[1] / source
    errors = [
        node
        for node in ast.walk(ast.parse(file.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "HTTPException"
    ]
    assert errors
    for error in errors:
        detail = error.args[1]
        assert isinstance(detail, ast.Call) and isinstance(detail.func, ast.Name)
        assert detail.func.id == "Message", (file, error.lineno)


def test_security_errors_follow_request_language_and_release_capacity():
    from starlette.responses import JSONResponse

    from app.http_security import HttpSecurity

    async def exercise():
        async def endpoint(scope, receive, send):
            await JSONResponse({"ok": True})(scope, receive, send)

        app = HttpSecurity(endpoint, json_limit=8, expensive_limit=1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            oversized = await client.post(
                "/api/preview", content=b"x" * 9, headers={"Accept-Language": "de-DE"}
            )
            assert oversized.status_code == 413
            assert oversized.json()["detail"] == "Der Anfrageinhalt ist zu groß."
            assert app.slots.acquire(blocking=False)
            try:
                busy = await client.post(
                    "/api/preview", content=b"{}", headers={"Accept-Language": "de"}
                )
                assert busy.status_code == 503
                assert (
                    busy.json()["detail"]
                    == "Die Bilderzeugung ist ausgelastet. Versuche es gleich erneut."
                )
                assert busy.headers["retry-after"] == "1"
            finally:
                app.slots.release()
            assert (await client.post("/api/preview", content=b"{}")).status_code == 200
            fallback = await client.post(
                "/api/preview", content=b"x" * 9, headers={"Accept-Language": "../de,fr"}
            )
            assert fallback.json()["detail"] == "Request body is too large"

    anyio.run(exercise)


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


def test_localized_avatar_failure_preserves_picture_and_allows_retry(auth_client, tmp_path):
    import io

    from PIL import Image

    client = auth_client
    setup_admin(client, tmp_path)
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, format="PNG")
    assert client.put("/api/auth/avatar", content=image.getvalue()).status_code == 200
    original = client.get("/api/auth/avatar").content
    response = client.put(
        "/api/auth/avatar", content=b"invalid image", headers={"Accept-Language": "de"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Das Bild konnte nicht dekodiert werden"
    assert client.get("/api/auth/avatar").content == original
    replacement = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(replacement, format="PNG")
    assert client.put("/api/auth/avatar", content=replacement.getvalue()).status_code == 200
    assert client.get("/api/auth/avatar").content != original


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
    denied = client.put("/api/auth/language", json=body, headers={"Accept-Language": "de"})
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Melde dich an, um deine Sprache zu ändern"
    fallback = client.put("/api/auth/language", json=body, headers={"Accept-Language": "fr"})
    assert fallback.status_code == 401
    assert fallback.json()["detail"] == "Sign in to change your language"
    setup_admin(client, tmp_path)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.put("/api/auth/language", json=body).status_code == 403
    denied = client.put("/api/auth/language", json=body, headers={"Accept-Language": "de"})
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Fehlendes oder ungültiges CSRF-Token."
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
