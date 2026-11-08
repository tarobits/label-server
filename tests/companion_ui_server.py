"""Local browser fixture: outbound HTTP is real, physical printers are simulated."""

import os
from tempfile import TemporaryDirectory

import uvicorn
from printer_factory import browser_printer

from companion.agent import Agent
from companion.config import Settings
from companion.journal import Journal
from companion.web import create_app

if __name__ == "__main__":
    with TemporaryDirectory(prefix="label-station-ui-") as directory:
        settings = Settings(data_dir=directory)  # type: ignore[call-arg]
        agent = Agent(settings, Journal(settings.data_dir / "journal.db"), backend_factory=browser_printer)
        uvicorn.run(create_app(settings, agent), host="127.0.0.1", port=int(os.environ["LABEL_STATION_UI_PORT"]), access_log=False)
