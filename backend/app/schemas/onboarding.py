from pydantic import BaseModel, Field, SecretStr


class SshOnboardingCreate(BaseModel):
    name: str
    host: str
    root_password: SecretStr
    ssh_host_key_fingerprint: str | None = None
    agent_port: int = Field(default=8443, ge=1, le=65535)


class SshOnboardingResponse(BaseModel):
    node_id: int
    lifecycle_status: str
    ssh_host_key_fingerprint: str | None
    bootstrap_expires_at: str
    bootstrap_window_expires_at: str
    warning: str | None = None
