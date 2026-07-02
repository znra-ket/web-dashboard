from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    agent_version: str = "0.1.0"
    script_storage_dir: Path = Path("data/scripts")
    workdir_root: Path = Path("data/work")
    max_script_upload_bytes: int = 1024 * 1024
    default_timeout_seconds: int = 60
    max_timeout_seconds: int = 600

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WEBXRAY_AGENT_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
