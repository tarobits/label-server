import asyncio
import io
import time
from threading import Event, Timer

import httpx
import pytest
from app_client import TestClient
from PIL import Image
from sqlalchemy import delete
from test_access_security import accounts as accounts
from test_companion_auth import station
from test_companion_station import local_station

from app.authn.avatars import avatar_version, normalize_avatar
from app.models import ResourceGrant, User
from companion.web import create_app


def picture():
    output = io.BytesIO()
    source = Image.new("RGB", (400, 200), "blue")
    source.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("blocked_stage", ["normalize", "lock"])
def test_avatar_upload_keeps_event_loop_responsive(accounts, monkeypatch, blocked_stage):
    import app.authn.avatar_api as api

    admin, alice, _ = accounts
    entered, release = Event(), Event()
    original = api.normalize_avatar

    def normalize(data):
        entered.set()
        if blocked_stage == "normalize":
            release.wait(3)
        return original(data)

    monkeypatch.setattr(api, "normalize_avatar", normalize)
    lock = admin.app.state.fleet.lock
    if blocked_stage == "lock":
        lock.acquire()

    def unblock():
        release.set()
        if blocked_stage == "lock" and lock.locked():
            lock.release()

    # A bounded external escape prevents the regression itself deadlocking the test.
    fallback = Timer(3, unblock)
    fallback.start()

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admin.app),
            base_url="http://testserver",
            cookies=alice.cookies,
            headers={"X-CSRF-Token": alice.headers["X-CSRF-Token"]},
        ) as client:
            started = time.monotonic()
            upload = asyncio.create_task(client.put("/api/auth/avatar", content=picture()))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                response = await asyncio.wait_for(client.get("/api/health"), 1)
                assert response.status_code == 200
                assert time.monotonic() - started < 2
            finally:
                unblock()
                result = await upload
            assert result.status_code == 200, result.text

    try:
        asyncio.run(run())
    finally:
        unblock()
        fallback.cancel()
        fallback.join()


def test_account_picture_is_sanitized_private_replaceable_and_removable(accounts):
    admin, alice, bob = accounts
    assert alice.get("/api/auth/avatar/info").json() == {"avatar_version": None}
    response = alice.put("/api/auth/avatar", content=picture())
    assert response.status_code == 200, response.text
    assert response.json()["avatar_version"]
    result = alice.get("/api/auth/avatar")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    decoded = Image.open(io.BytesIO(result.content))
    assert decoded.size == (256, 256) and decoded.format == "PNG"
    assert not decoded.info
    assert bob.get("/api/auth/avatar").status_code == 404
    assert admin.get("/api/auth/avatar").status_code == 404
    assert alice.put("/api/auth/avatar", content=b"not an image").status_code == 422
    assert alice.get("/api/auth/avatar").content == result.content
    assert (
        alice.put(
            "/api/auth/avatar", content=picture(), headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert alice.put("/api/auth/avatar", content=b"x" * 5_000_001).status_code == 413
    anonymous = TestClient(admin.app)
    assert anonymous.get("/api/auth/avatar").status_code == 401
    assert anonymous.put("/api/auth/avatar", content=picture()).status_code == 401
    anonymous.close()
    assert alice.delete("/api/auth/avatar").status_code == 204
    assert alice.get("/api/auth/avatar/info").json()["avatar_version"] is None
    assert alice.get("/api/auth/avatar").status_code == 404


def test_oversized_upload_can_be_retried_with_portrait_png(accounts):
    _, alice, _ = accounts
    assert alice.put("/api/auth/avatar", content=b"x" * 5_000_001).status_code == 413
    assert alice.get("/api/auth/avatar/info").json()["avatar_version"] is None
    output = io.BytesIO()
    # Match the reported dimensions and alpha channel, without using a private photo.
    Image.new("RGBA", (935, 1004), (20, 40, 60, 180)).save(output, format="PNG")
    response = alice.put("/api/auth/avatar", content=output.getvalue())
    assert response.status_code == 200, response.text
    assert response.json()["avatar_version"]
    decoded = Image.open(io.BytesIO(alice.get("/api/auth/avatar").content))
    assert decoded.size == (256, 256)
    assert alice.get("/api/health").status_code == 200


@pytest.mark.parametrize("size", [(8193, 1), (4001, 4000)])
def test_profile_picture_pixel_limits(size):
    output = io.BytesIO()
    Image.new("L", size).save(output, format="PNG")
    with pytest.raises(ValueError, match="megapixels"):
        normalize_avatar(output.getvalue())


def test_companion_picture_access_follows_current_user_access_and_binding(accounts, tmp_path):
    admin, alice, bob = accounts
    assert alice.put("/api/auth/avatar", content=picture()).status_code == 200
    assert bob.put("/api/auth/avatar", content=picture()).status_code == 200
    settings, agent = local_station(admin, tmp_path, user="alice")
    with TestClient(create_app(settings, agent, start_agent=False)) as local:
        state = local.get("/api/station").json()
        assert state["locked"] and state["users"][0]["avatar_version"]
        assert (
            local.get("/api/station/users/alice/avatar").content
            == alice.get("/api/auth/avatar").content
        )
        assert local.get("/api/station/users/bob/avatar").status_code == 404
        # A stale picker list cannot bypass a fresh access check on the main server.
        with admin.app.state.factory.begin() as session:
            session.execute(delete(ResourceGrant).where(ResourceGrant.scope_kind == "companion"))
        assert local.get("/api/station/users/alice/avatar").status_code == 403


def test_picture_requires_station_key_and_picker_eligibility(accounts):
    admin, alice, _ = accounts
    alice.put("/api/auth/avatar", content=picture())
    _, headers, _ = station(admin)
    assert admin.get("/api/companion/users/alice/avatar").status_code == 401
    assert admin.get("/api/companion/users/alice/avatar", headers=headers).status_code == 404
    with admin.app.state.factory.begin() as session:
        session.get(User, "alice").disabled = True
    assert admin.get("/api/companion/users/alice/avatar", headers=headers).status_code == 403


def test_account_purge_removes_picture(accounts):
    import time

    from app.maintenance.deletion import delete_account, purge_expired

    admin, alice, _ = accounts
    alice.put("/api/auth/avatar", content=picture())
    with admin.app.state.factory() as session:
        assert avatar_version(session, "alice")
    with admin.app.state.factory.begin() as session:
        delete_account(
            session,
            session.get(User, "alice"),
            "administrator",
            admin.app.state.fonts,
            admin.app.state.images,
        )
        purge_expired(
            session, admin.app.state.fonts, admin.app.state.images, time.time() + 100 * 86400
        )
    with admin.app.state.factory() as session:
        assert avatar_version(session, "alice") is None
