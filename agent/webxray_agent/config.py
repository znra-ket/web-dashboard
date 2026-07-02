from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    agent_version: str = "0.1.0"
    script_storage_dir: Path = Path("data/scripts")
    workdir_root: Path = Path("data/work")
    pairing_state_dir: Path = Path("data/pairing")
    bootstrap_state_dir: Path | None = None
    install_root: Path = Path(".")
    uninstall_dry_run: bool = True
    max_script_upload_bytes: int = 1024 * 1024
    default_timeout_seconds: int = 60
    max_timeout_seconds: int = 600
    max_args_count: int = 64
    max_single_arg_bytes: int = 16 * 1024
    max_args_total_bytes: int = 64 * 1024
    max_env_count: int = 64
    max_env_key_bytes: int = 128
    max_single_env_value_bytes: int = 16 * 1024
    max_env_total_bytes: int = 64 * 1024
    max_stdout_bytes: int = 256 * 1024
    max_stderr_bytes: int = 256 * 1024
    max_concurrent_executions_global: int = 2
    max_concurrent_executions_per_hash: int = 1
    request_id_cache_ttl_seconds: int = 3600
    request_id_cache_max_entries: int = 1024
    shutdown_grace_seconds: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WEBXRAY_AGENT_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
