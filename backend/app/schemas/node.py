from pydantic import BaseModel, Field

from app.models.node import NodeLifecycleStatus


class NodeCreate(BaseModel):
    name: str
    host: str
    agent_port: int = Field(default=8443, ge=1, le=65535)
    lifecycle_status: NodeLifecycleStatus = NodeLifecycleStatus.INSTALLING_AGENT
    agent_cert_fingerprint: str | None = None
    ssh_host_key_fingerprint: str | None = None
