"""Only the restricted token file's location is logged during enrollment."""

import logging

from test_auth import auth_client as auth_client_fixture
from test_auth import setup_admin

from app.auth import initialize_auth

auth_client = auth_client_fixture


def test_setup_token_location_is_logged_without_secret(auth_client, tmp_path, caplog):
    path = tmp_path / "auth-setup-token"
    path.unlink()
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        caplog.clear()
        initialize_auth(auth_client.app.state.factory, tmp_path)
        token = path.read_text().strip()
        assert caplog.messages == [f"Initial administrator setup token is available in {path}"]
        assert token not in caplog.text
        caplog.clear()
        initialize_auth(auth_client.app.state.factory, tmp_path)
        assert path.read_text().strip() == token
        assert caplog.messages == [f"Initial administrator setup token is available in {path}"]
        assert token not in caplog.text
        setup_admin(auth_client, tmp_path)
        caplog.clear()
        initialize_auth(auth_client.app.state.factory, tmp_path)
        assert not path.exists()
        assert caplog.messages == []
