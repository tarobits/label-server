"""Isolated backend for browser tests; never opens the user's database or ntfy."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from alembic import command
from alembic.config import Config
from conftest import create_test_app as create_app
from fastapi import Body, Request
from fastapi.responses import HTMLResponse
from printer_factory import browser_printer

from app import notification_routing, push_api, recovery_api
from app.admin_api import DB
from app.auth import hash_password
from app.config import Settings
from app.identity import LOCAL_OWNER_ID
from app.models import User
from app.push_delivery import generate_key

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="label-printer-ui-") as directory:
        url = f"sqlite:///{directory}/labels.db"
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        config.attributes["database_url"] = url
        command.upgrade(config, "head")
        port = int(os.environ.get("LABEL_UI_PORT", "8765"))
        push_key = Path(directory) / "vapid.pem"
        generate_key(push_key)
        settings = Settings(
            vapid_private_key_file=push_key,
            vapid_subject="mailto:ui-tests@example.invalid",
            check_for_updates=False,
            database_url=url,
            worker_interval_seconds=0.1,
            frontend_dist=Path(
                os.environ.get("LABEL_UI_FRONTEND_DIST", root / "frontend" / "dist")
            ),
            public_url=f"http://127.0.0.1:{port}",
            smtp_host="smtp.example.invalid",
            smtp_from="labels@example.invalid",
        )
        messages: list[dict[str, str]] = []
        pushes: list[dict[str, str]] = []

        def capture_push(settings, endpoint, notice):
            pushes.append(
                {
                    "device": endpoint.id,
                    "title": notice.title,
                    "body": notice.message,
                    "path": notice.path,
                    "tag": notice.id,
                }
            )

        push_api.send_push = capture_push
        notification_routing.send_push = capture_push

        def capture_email(settings, recipient, subject, body):
            messages.append({"recipient": recipient, "subject": subject, "body": body})

        # Isolated browser fixtures never contact a real mail server.
        recovery_api.send_email = capture_email
        notification_routing.send_email = capture_email
        application = create_app(settings, backend_factory=browser_printer)
        application.state.access_policy = None

        outage_status: int | None = None

        @application.middleware("http")
        async def simulate_proxy_outage(request: Request, call_next):
            if outage_status is not None and request.url.path != "/api/test/outage":
                return HTMLResponse(
                    "<html><body>Cloudflare error 1033: tunnel unavailable</body></html>",
                    status_code=outage_status,
                    headers={"Cache-Control": "no-store"},
                )
            return await call_next(request)

        @application.post("/api/test/outage")
        def set_outage(status: int | None = Body(default=None, embed=True)):
            # This control exists only in the isolated browser-test process.
            global outage_status
            outage_status = status
            return {"status": outage_status}

        @application.get("/api/test/pushes")
        def captured_pushes(session: DB):
            return pushes

        @application.get("/api/test/emails")
        def captured_emails(session: DB):
            return messages

        with application.state.factory.begin() as session:
            session.add(
                User(
                    id=LOCAL_OWNER_ID,
                    username="owner",
                    password_hash=hash_password("browser-owner-password"),
                    role_ids=["administrator"],
                )
            )
        uvicorn.run(
            application,
            host="127.0.0.1",
            port=port,
        )
