"""Isolated backend for browser tests; never opens the user's database or ntfy."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from alembic import command
from alembic.config import Config

from app.config import Settings
from app.main import create_app

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="label-printer-ui-") as directory:
        url = f"sqlite:///{directory}/labels.db"
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        config.attributes["database_url"] = url
        command.upgrade(config, "head")
        settings = Settings(
            printer_backend="mock",
            database_url=url,
            worker_interval_seconds=0.1,
            ntfy_url="",
            ntfy_topic="",
            ntfy_token="",
            frontend_dist=root / "frontend" / "dist",
        )
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8765)
