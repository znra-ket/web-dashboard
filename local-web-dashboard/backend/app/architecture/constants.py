from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping


NODE_LIFECYCLE_STATES_V1: tuple[str, ...] = (
    "installing_agent",
    "bootstrap_pending",
    "mtls_pairing",
    "metrics_uploading",
    "active",
    "failed_install",
    "failed_bootstrap_timeout",
    "failed_mtls_pairing",
    "failed_metrics_upload",
    "unpairing",
    "uninstalling",
    "deleting_local",
)

TRIGGER_TYPES_V1: tuple[str, ...] = ("schedule", "on_startup")

MAX_PIPELINE_STEPS = 32

BOOTSTRAP_TOKEN_BYTES = 32
BOOTSTRAP_TOKEN_TTL_SECONDS = 15 * 60
BOOTSTRAP_ABSOLUTE_WINDOW_SECONDS = 30 * 60

AGENT_FEATURES_V1: tuple[str, ...] = (
    "script_upload",
    "script_execute",
    "script_delete",
    "admin_unpair",
    "admin_uninstall",
)


@dataclass(frozen=True, slots=True)
class AgentLimitsV1:
    max_script_upload_bytes: int
    max_agent_script_storage_bytes: int
    max_execute_body_bytes: int
    max_args_count: int
    max_single_arg_bytes: int
    max_args_total_bytes: int
    max_env_count: int
    max_env_key_bytes: int
    max_single_env_value_bytes: int
    max_env_total_bytes: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    default_timeout_seconds: int
    max_timeout_seconds: int
    speedtest_timeout_seconds: int
    shutdown_grace_seconds: int
    max_concurrent_executions_global: int
    max_concurrent_executions_per_hash: int
    request_id_cache_ttl_seconds: int
    request_id_cache_max_entries: int
    max_processes_per_run: int
    max_open_files_per_run: int
    max_memory_bytes_per_run: int
    workdir_quota_bytes_per_run: int

    def as_mapping(self) -> Mapping[str, int]:
        return MappingProxyType(asdict(self))


AGENT_LIMITS_V1 = AgentLimitsV1(
    max_script_upload_bytes=1 * 1024 * 1024,
    max_agent_script_storage_bytes=64 * 1024 * 1024,
    max_execute_body_bytes=128 * 1024,
    max_args_count=64,
    max_single_arg_bytes=16 * 1024,
    max_args_total_bytes=64 * 1024,
    max_env_count=64,
    max_env_key_bytes=128,
    max_single_env_value_bytes=16 * 1024,
    max_env_total_bytes=64 * 1024,
    max_stdout_bytes=256 * 1024,
    max_stderr_bytes=256 * 1024,
    default_timeout_seconds=60,
    max_timeout_seconds=600,
    speedtest_timeout_seconds=180,
    shutdown_grace_seconds=5,
    max_concurrent_executions_global=2,
    max_concurrent_executions_per_hash=1,
    request_id_cache_ttl_seconds=3600,
    request_id_cache_max_entries=1024,
    max_processes_per_run=32,
    max_open_files_per_run=64,
    max_memory_bytes_per_run=256 * 1024 * 1024,
    workdir_quota_bytes_per_run=64 * 1024 * 1024,
)
