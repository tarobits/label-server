"""Exercise group funding/receipts against an isolated real MariaDB database."""

import secrets
import time

import pytest
from app_client import TestClient
from conftest import seed_test_printer
from mock_backend import MockPrinterBackend
from printer_factory import test_printer as printer_factory
from test_group_billing import (
    test_payment_report_requires_creditor_confirmation_and_is_idempotent as payment_flow,
)
from test_group_billing import (
    test_risk_partial_payment_becomes_transfer_and_reimbursement_once as risk_flow,
)
from test_mariadb import maria_engine as maria_engine
from test_mariadb import upgrade

from app.authn.auth import COOKIE_NAME, token_hash
from app.config import Settings
from app.main import create_app
from app.models import AuthSession, LabelTemplate, Role, User


@pytest.mark.parametrize("flow", [payment_flow, risk_flow])
def test_group_funding_and_receipts_on_mariadb(maria_engine, flow, tmp_path):
    url = maria_engine.url.render_as_string(hide_password=False)
    upgrade(url)
    seed_test_printer(url)
    app = create_app(
        Settings(database_url=url, data_dir=tmp_path / "state"),
        {"main": MockPrinterBackend()},
        start_worker=False,
        backend_factory=printer_factory,
    )
    with TestClient(app) as admin:
        alice, bob = TestClient(app), TestClient(app)
        with app.state.factory.begin() as session:
            session.get(LabelTemplate, "text").scope = "global"
        for client, name in ((admin, "administrator"), (alice, "alice"), (bob, "bob")):
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            with app.state.factory.begin() as session:
                if name != "administrator":
                    session.add(Role(id=f"{name}-access", name=f"{name} access", permissions=[]))
                session.add(
                    User(
                        id=name,
                        username=name,
                        password_hash="fixture-hash",
                        role_ids=["administrator"]
                        if name == "administrator"
                        else ["member", f"{name}-access"],
                    )
                )
                session.flush()
                session.add(
                    AuthSession(
                        token_hash=token_hash(token),
                        user_id=name,
                        csrf_token=csrf,
                        expires_at=time.time() + 3600,
                    )
                )
            client.cookies.set(COOKIE_NAME, token)
            client.headers["X-CSRF-Token"] = csrf
        try:
            flow((admin, alice, bob))
        finally:
            alice.close()
            bob.close()
