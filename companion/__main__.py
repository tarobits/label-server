import uvicorn

from companion.config import Settings
from companion.web import create_app


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]  # Required values come from deployment environment.
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port, workers=1, access_log=False
    )


if __name__ == "__main__":
    main()
