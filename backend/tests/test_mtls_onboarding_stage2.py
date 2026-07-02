import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.bootstrap import BootstrapTokenStatus
from app.models.node import Node, NodeLifecycleStatus
from app.schemas.node import NodeCreate
from app.services.bootstrap_token_service import issue_bootstrap_token
from app.services.certificate_authority import certificate_fingerprint
from app.services.exceptions import AgentIntegrityMismatchError
from app.services.mtls_onboarding_service import (
    MtlsProbeResult,
    MtlsProbeService,
    Stage2MtlsOnboardingService,
)
from app.services.node_service import create_node


class Stage2MtlsOnboardingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_stage2_signs_certificate_saves_fingerprint_and_consumes_token(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.BOOTSTRAP_PENDING,
                ),
            )
            issued = await issue_bootstrap_token(session, node.id)
            agent = FakeBootstrapAgentClient()

            paired = await Stage2MtlsOnboardingService(session, agent).establish_mtls(
                node.id,
                issued.raw_token,
            )
            token = await session.get(type(issued.record), issued.record.id)

        self.assertEqual(agent.csr_calls, [(node.id, issued.raw_token)])
        self.assertEqual(agent.certificate_calls[0][0:2], (node.id, issued.raw_token))
        self.assertIn("BEGIN CERTIFICATE", agent.certificate_calls[0][2])
        self.assertEqual(paired.lifecycle_status, NodeLifecycleStatus.METRICS_UPLOADING.value)
        self.assertEqual(paired.agent_cert_fingerprint, certificate_fingerprint(agent.certificate_calls[0][2]))
        self.assertEqual(token.status, BootstrapTokenStatus.CONSUMED.value)

    async def test_mtls_probe_success_requires_valid_chain_and_matching_active_node(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                    agent_cert_fingerprint="sha256:abc",
                ),
            )

            ok = await MtlsProbeService(
                session,
                FakeProbeTransport(MtlsProbeResult(True, "sha256:abc")),
            ).probe_node(node.id)

        self.assertTrue(ok)

    async def test_mtls_probe_rejects_valid_chain_with_wrong_fingerprint(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                    agent_cert_fingerprint="sha256:expected",
                ),
            )

            with self.assertRaises(AgentIntegrityMismatchError):
                await MtlsProbeService(
                    session,
                    FakeProbeTransport(MtlsProbeResult(True, "sha256:other")),
                ).probe_node(node.id)

    async def test_mtls_probe_rejects_invalid_tls_chain_even_if_fingerprint_matches(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                    agent_cert_fingerprint="sha256:abc",
                ),
            )

            with self.assertRaises(AgentIntegrityMismatchError):
                await MtlsProbeService(
                    session,
                    FakeProbeTransport(MtlsProbeResult(False, "sha256:abc")),
                ).probe_node(node.id)

    async def test_mtls_probe_rejects_inactive_node(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.BOOTSTRAP_PENDING,
                    agent_cert_fingerprint="sha256:abc",
                ),
            )

            with self.assertRaises(AgentIntegrityMismatchError):
                await MtlsProbeService(
                    session,
                    FakeProbeTransport(MtlsProbeResult(True, "sha256:abc")),
                ).probe_node(node.id)


class FakeBootstrapAgentClient:
    def __init__(self) -> None:
        self._csr = _generate_csr()
        self.csr_calls = []
        self.certificate_calls = []

    async def bootstrap_csr(self, node: Node, bootstrap_token: str):
        self.csr_calls.append((node.id, bootstrap_token))
        return type("CsrResponse", (), {"csr": self._csr})()

    async def bootstrap_certificate(self, node: Node, bootstrap_token: str, certificate_pem: str):
        self.certificate_calls.append((node.id, bootstrap_token, certificate_pem))
        return type("CertificateResponse", (), {"status": "completed"})()


class FakeProbeTransport:
    def __init__(self, result: MtlsProbeResult) -> None:
        self._result = result

    async def probe(self, node: Node) -> MtlsProbeResult:
        return self._result


def _generate_csr() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"agent-{uuid4()}")]))
        .sign(private_key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
