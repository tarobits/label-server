"""Settings for tests that explicitly exclude the developer's environment file."""

from pydantic_settings import SettingsConfigDict

from app.config import Settings


class IsolatedSettings(Settings):
    model_config = SettingsConfigDict(env_file=None)
