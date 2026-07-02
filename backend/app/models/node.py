from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeLifecycleStatus(StrEnum):
    INSTALLING_AGENT = "installing_agent"
    BOOTSTRAP_PENDING = "bootstrap_pending"
    MTLS_PAIRING = "mtls_pairing"
    METRICS_UPLOADING = "metrics_uploading"
    ACTIVE = "active"
    FAILED_INSTALL = "failed_install"
    FAILED_BOOTSTRAP_TIMEOUT = "failed_bootstrap_timeout"
    FAILED_MTLS_PAIRING = "failed_mtls_pairing"
    FAILED_METRICS_UPLOAD = "failed_metrics_upload"
    UNPAIRING = "unpairing"
    UNINSTALLING = "uninstalling"
    DELETING_LOCAL = "deleting_local"


class Node(Base):
    __tablename__ = "node"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    agent_cert_fingerprint: Mapped[str | None] = mapped_column(String, unique=True)
