"""Isolated backend for browser tests; never opens the user's database or ntfy."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from alembic import command
from alembic.config import Config
from conftest import create_test_app as create_app
from printer_factory import browser_printer

from app.auth import hash_password
from app.config import Settings
from app.identity import LOCAL_OWNER_ID
from app.models import User

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="label-printer-ui-") as directory:
        url = f"sqlite:///{directory}/labels.db"
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        config.attributes["database_url"] = url
        command.upgrade(config, "head")
        settings = Settings(
            check_for_updates=False,
            database_url=url,
            worker_interval_seconds=0.1,
            frontend_dist=root / "frontend" / "dist",
        )
        application = create_app(settings, backend_factory=browser_printer)
        application.state.access_policy = None
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
            port=int(os.environ.get("LABEL_UI_PORT", "8765")),
        )
