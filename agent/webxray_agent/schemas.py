from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InfoResponse(BaseModel):
    agent_version: str
    api_version: int
    supported_features: list[str]
    limits: dict[str, int]


class ScriptUploadRequest(BaseModel):
    script_source: str

    model_config = ConfigDict(extra="ignore")


class ScriptUploadResponse(BaseModel):
    hash: str


class ScriptExecuteRequest(BaseModel):
    hash: str
    request_id: UUID
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int | None = None


class ScriptExecuteResponse(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
