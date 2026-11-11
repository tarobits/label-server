import uvicorn

from companion.config import Settings
from companion.web import create_app


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]  # Required values come from deployment environment.
    uvicorn.run(
        lambda: create_app(settings),
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=1,
        log_level=settings.log_level.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
