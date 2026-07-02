import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.bootstrap import NodeBootstrapToken
from app.models.node import Node, NodeLifecycleStatus
from app.schemas.onboarding import SshOnboardingCreate
from app.services.exceptions import AgentInstallError, SshHostKeyMismatchError
from app.services.onboarding_service import Stage1OnboardingService
from app.services.ssh_installer import SshConnection


class Stage1OnboardingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_strict_fingerprint_success_installs_agent(self) -> None:
        async with self.session_maker() as session:
            ssh = FakeSshConnector(actual_fingerprint="SHA256:expected")
            installer = FakeInstaller()
            result = await Stage1OnboardingService(session, ssh, installer).install_agent_over_ssh(
                SshOnboardingCreate(
                    name="node-1",
                    host="203.0.113.10",
                    root_password="secret",
                    ssh_host_key_fingerprint="SHA256:expected",
                )
            )
            node = await session.get(Node, result.node.id)
            bootstrap_rows = await _bootstrap_rows(session)

        self.assertEqual(node.lifecycle_status, NodeLifecycleStatus.BOOTSTRAP_PENDING.value)
        self.assertEqual(node.ssh_host_key_fingerprint, "SHA256:expected")
        self.assertEqual(len(bootstrap_rows), 1)
        self.assertNotEqual(bootstrap_rows[0].token_hash, result.raw_bootstrap_token)
        self.assertNotIn(result.raw_bootstrap_token, repr(bootstrap_rows[0].__dict__))
        self.assertIsNone(result.warning)
        self.assertEqual(ssh.events, ["host_key_checked", "password_used"])
        self.assertEqual(installer.install_calls, 1)
        self.assertEqual(installer.bootstrap_token_hash, bootstrap_rows[0].token_hash)
        self.assertEqual(installer.bootstrap_expires_at, bootstrap_rows[0].expires_at)
        self.assertNotEqual(installer.bootstrap_token_hash, result.raw_bootstrap_token)
        self.assertTrue(ssh.session.closed)

    async def test_strict_fingerprint_failure_happens_before_password(self) -> None:
        async with self.session_maker() as session:
            ssh = FakeSshConnector(actual_fingerprint="SHA256:actual")
            installer = FakeInstaller()

            with self.assertRaises(SshHostKeyMismatchError):
                await Stage1OnboardingService(session, ssh, installer).install_agent_over_ssh(
                    SshOnboardingCreate(
                        name="node-1",
                        host="203.0.113.10",
                        root_password="secret",
                        ssh_host_key_fingerprint="SHA256:expected",
                    )
                )

            node = await _node_by_name(session, "node-1")

        self.assertEqual(node.lifecycle_status, NodeLifecycleStatus.FAILED_INSTALL.value)
        self.assertIsNone(node.ssh_host_key_fingerprint)
        self.assertEqual(ssh.events, ["host_key_checked"])
        self.assertEqual(installer.install_calls, 0)

    async def test_tofu_mode_saves_fingerprint_and_returns_warning(self) -> None:
        async with self.session_maker() as session:
            ssh = FakeSshConnector(actual_fingerprint="SHA256:tofu")
            result = await Stage1OnboardingService(session, ssh, FakeInstaller()).install_agent_over_ssh(
                SshOnboardingCreate(
                    name="node-1",
                    host="203.0.113.10",
                    root_password="secret",
                )
            )
            node = await session.get(Node, result.node.id)

        self.assertEqual(node.lifecycle_status, NodeLifecycleStatus.BOOTSTRAP_PENDING.value)
        self.assertEqual(node.ssh_host_key_fingerprint, "SHA256:tofu")
        self.assertEqual(result.warning, "SSH host key fingerprint accepted via TOFU")

    async def test_root_password_is_not_stored_on_node(self) -> None:
        async with self.session_maker() as session:
            result = await Stage1OnboardingService(
                session,
                FakeSshConnector(actual_fingerprint="SHA256:tofu"),
                FakeInstaller(),
            ).install_agent_over_ssh(
                SshOnboardingCreate(
                    name="node-1",
                    host="203.0.113.10",
                    root_password="super-secret-root-password",
                )
            )
            node = await session.get(Node, result.node.id)

        self.assertFalse(hasattr(node, "root_password"))
        self.assertNotIn("super-secret-root-password", repr(node.__dict__))

    async def test_failed_install_sets_failed_install_status(self) -> None:
        async with self.session_maker() as session:
            ssh = FakeSshConnector(actual_fingerprint="SHA256:expected")
            installer = FakeInstaller(raise_error=True)

            with self.assertRaises(AgentInstallError):
                await Stage1OnboardingService(session, ssh, installer).install_agent_over_ssh(
                    SshOnboardingCreate(
                        name="node-1",
                        host="203.0.113.10",
                        root_password="secret",
                        ssh_host_key_fingerprint="SHA256:expected",
                    )
                )

            node = await _node_by_name(session, "node-1")

        self.assertEqual(node.lifecycle_status, NodeLifecycleStatus.FAILED_INSTALL.value)
        self.assertEqual(node.ssh_host_key_fingerprint, "SHA256:expected")
        self.assertTrue(ssh.session.closed)


class FakeSshConnector:
    def __init__(self, actual_fingerprint: str) -> None:
        self.actual_fingerprint = actual_fingerprint
        self.events = []
        self.session = FakeSshSession()

    async def connect_root(
        self,
        host: str,
        root_password: str,
        expected_host_key_fingerprint: str | None,
    ) -> SshConnection:
        self.events.append("host_key_checked")
        if (
            expected_host_key_fingerprint is not None
            and expected_host_key_fingerprint != self.actual_fingerprint
        ):
            raise SshHostKeyMismatchError("SSH host key fingerprint mismatch")

        self.events.append("password_used")
        warning = None
        if expected_host_key_fingerprint is None:
            warning = "SSH host key fingerprint accepted via TOFU"

        return SshConnection(
            session=self.session,
            host_key_fingerprint=self.actual_fingerprint,
            warning=warning,
        )


class FakeSshSession:
    def __init__(self) -> None:
        self.closed = False

    async def run(self, command: str, input: str | None = None, check: bool = True) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeInstaller:
    def __init__(self, raise_error: bool = False) -> None:
        self.raise_error = raise_error
        self.install_calls = 0
        self.bootstrap_token_hash = None
        self.bootstrap_expires_at = None

    async def install(
        self,
        session: FakeSshSession,
        bootstrap_token_hash: str,
        bootstrap_expires_at: str,
    ) -> None:
        self.install_calls += 1
        self.bootstrap_token_hash = bootstrap_token_hash
        self.bootstrap_expires_at = bootstrap_expires_at
        if self.raise_error:
            raise AgentInstallError("install failed")


async def _node_by_name(session, name: str) -> Node:
    result = await session.execute(select(Node).where(Node.name == name))
    return result.scalar_one()


async def _bootstrap_rows(session) -> list[NodeBootstrapToken]:
    result = await session.execute(select(NodeBootstrapToken).order_by(NodeBootstrapToken.id))
    return list(result.scalars().all())
