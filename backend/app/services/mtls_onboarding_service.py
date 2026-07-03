from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeLifecycleStatus
from app.services.bootstrap_token_service import complete_bootstrap
from app.services.certificate_authority import DashboardCertificateAuthority
from app.services.exceptions import AgentIntegrityMismatchError, NotFoundError

if TYPE_CHECKING:
    from app.agent_client import AgentClient


class MtlsProbeTransport(Protocol):
    async def probe(self, node: Node) -> "MtlsProbeResult": ...


@dataclass(frozen=True)
class MtlsProbeResult:
    tls_chain_valid: bool
    peer_certificate_fingerprint: str


class Stage2MtlsOnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        agent_client: AgentClient,
        ca: DashboardCertificateAuthority | None = None,
    ) -> None:
        self._session = session
        self._agent_client = agent_client
        self._ca = ca or DashboardCertificateAuthority()

    async def establish_mtls(self, node_id: int, bootstrap_token: str) -> Node:
        node = await self._session.get(Node, node_id)
        if node is None:
            raise NotFoundError(f"Node {node_id} not found")

        node.lifecycle_status = NodeLifecycleStatus.MTLS_PAIRING.value
        await self._session.commit()
        await self._session.refresh(node)

        csr_response = await self._agent_client.bootstrap_csr(node, bootstrap_token)
        signed = self._ca.sign_agent_csr(csr_response.csr)
        await self._agent_client.bootstrap_certificate(
            node,
            bootstrap_token,
            signed.certificate_pem,
        )
        await complete_bootstrap(self._session, node.id, bootstrap_token)

        node.agent_cert_fingerprint = signed.fingerprint
        node.lifecycle_status = NodeLifecycleStatus.METRICS_UPLOADING.value
        await self._session.commit()
        await self._session.refresh(node)
        return node


class MtlsProbeService:
    def __init__(self, session: AsyncSession, probe_transport: MtlsProbeTransport) -> None:
        self._session = session
        self._probe_transport = probe_transport

    async def probe_node(self, node_id: int) -> bool:
        node = await self._session.get(Node, node_id)
        if node is None:
            raise NotFoundError(f"Node {node_id} not found")

        result = await self._probe_transport.probe(node)
        if not result.tls_chain_valid:
            raise AgentIntegrityMismatchError("mTLS probe failed: TLS chain is invalid")
        if node.lifecycle_status != NodeLifecycleStatus.ACTIVE.value:
            raise AgentIntegrityMismatchError("mTLS probe failed: node is not active")
        if node.agent_cert_fingerprint != result.peer_certificate_fingerprint:
            raise AgentIntegrityMismatchError("mTLS probe failed: peer certificate fingerprint mismatch")
        return True

    async def is_active_fingerprint_trusted(self, fingerprint: str) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        Node.lifecycle_status == NodeLifecycleStatus.ACTIVE.value,
                        Node.agent_cert_fingerprint == fingerprint,
                    )
                )
            )
        )
