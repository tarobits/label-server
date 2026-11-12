"""Import legacy main-server assets with the service stopped; archive verified source files after import."""

import argparse
import fcntl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assets.asset_import import archive_legacy_assets, import_assets  # noqa: E402
from app.config import Settings  # noqa: E402
from app.database_lock import database_owner  # noqa: E402
from app.db import make_engine, session_factory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    from app.deployment import require_role

    require_role("main")
    settings = Settings(**{"_env_file": args.env_file})
    engine = make_engine(settings.database_url)
    settings.state_directory.mkdir(parents=True, exist_ok=True)
    try:
        with settings.worker_lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error("Stop the main server before importing assets")
            factory = session_factory(engine)
            with database_owner(engine, enforce=True):
                with factory.begin() as session:
                    import_assets(session, settings.state_directory / "assets")
                archived = archive_legacy_assets(factory, settings.state_directory / "assets")
        print("Asset import verified.")
        if archived:
            print(f"Original files archived to: {archived}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
