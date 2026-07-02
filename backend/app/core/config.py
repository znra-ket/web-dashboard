from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "web-xray-dashboard"
    environment: str = "development"
    database_url: str = Field(
        default_factory=lambda: f"sqlite+aiosqlite:///{Path('vpn_dashboard.db').resolve().as_posix()}"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WEB_XRAY_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
