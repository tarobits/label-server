import io

import pytest
from app_client import TestClient
from PIL import Image
from sqlalchemy import delete
from test_access_security import accounts as accounts
from test_companion_auth import station
from test_companion_station import local_station

from app.avatars import avatar_path, normalize_avatar
from app.models import ResourceGrant, User
from companion.web import create_app


def picture():
    output = io.BytesIO()
    source = Image.new("RGB", (400, 200), "blue")
    source.save(output, format="PNG")
    return output.getvalue()


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

    from app.deletion import delete_account, purge_expired

    admin, alice, _ = accounts
    alice.put("/api/auth/avatar", content=picture())
    path = avatar_path(admin.app.state.images.root.parent, "alice")
    assert path.exists()
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
    assert not path.exists()
