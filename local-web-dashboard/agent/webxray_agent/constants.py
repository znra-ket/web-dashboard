from backend.app.architecture.constants import AGENT_LIMITS_V1


AGENT_STATES_V1: tuple[str, ...] = (
    "bootstrap_pending",
    "paired",
    "unpaired",
)

MAX_SCRIPT_UPLOAD_BYTES = AGENT_LIMITS_V1.max_script_upload_bytes
MAX_AGENT_SCRIPT_STORAGE_BYTES = AGENT_LIMITS_V1.max_agent_script_storage_bytes
