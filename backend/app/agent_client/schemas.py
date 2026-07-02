from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentInfoResponse(BaseModel):
    agent_version: str
    api_version: int
    supported_features: list[str]
    limits: dict[str, int]


class AgentScriptUploadRequest(BaseModel):
    script_source: str


class AgentScriptUploadResponse(BaseModel):
    hash: str


class AgentScriptExecuteRequest(BaseModel):
    hash: str
    request_id: UUID
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int | None = None


class AgentScriptExecuteResponse(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    error_class: str | None = None
    stderr_truncated: bool = False


class AgentAdminUnpairResponse(BaseModel):
    agent_state: str
    removed_paths: list[str]

    model_config = ConfigDict(extra="ignore")


class AgentAdminUninstallResponse(BaseModel):
    agent_state: str
    dry_run: bool
    planned_paths: list[str]
    removed_paths: list[str]

    model_config = ConfigDict(extra="ignore")


class AgentBootstrapStatusResponse(BaseModel):
    status: str
    expires_at: str | None


class AgentBootstrapCsrResponse(BaseModel):
    csr: str


class AgentBootstrapCertificateRequest(BaseModel):
    certificate_pem: str


class AgentBootstrapCertificateResponse(BaseModel):
    status: str
