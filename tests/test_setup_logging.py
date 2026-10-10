"""The local enrollment token is logged only while first-run setup is pending."""

import logging

from test_auth import auth_client as auth_client_fixture
from test_auth import setup_admin

from app.auth import initialize_auth

auth_client = auth_client_fixture


def test_setup_token_is_logged_on_creation_and_pending_restarts_only(auth_client, tmp_path, caplog):
    path = tmp_path / "auth-setup-token"
    path.unlink()
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        caplog.clear()
        initialize_auth(auth_client.app.state.factory, tmp_path)
        token = path.read_text().strip()
        assert caplog.messages == [f"Initial administrator setup token: {token}"]
        caplog.clear()
        initialize_auth(auth_client.app.state.factory, tmp_path)
        assert path.read_text().strip() == token
        assert caplog.messages == [f"Initial administrator setup token: {token}"]
        setup_admin(auth_client, tmp_path)
        caplog.clear()
        initialize_auth(auth_client.app.state.factory, tmp_path)
        assert not path.exists()
        assert caplog.messages == []
