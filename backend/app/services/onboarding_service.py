from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeLifecycleStatus
from app.models.bootstrap import NodeBootstrapToken
from app.models.bootstrap import BootstrapTokenStatus
from app.schemas.onboarding import SshOnboardingCreate
from app.services.bootstrap_token_service import issue_bootstrap_token
from app.services.exceptions import AgentInstallError, OnboardingError
from app.services.ssh_installer import AgentInstaller, AsyncSshConnector, ShellAgentInstaller, SshConnector


@dataclass(frozen=True)
class SshOnboardingResult:
    node: Node
    raw_bootstrap_token: str
    bootstrap_record: NodeBootstrapToken
    warning: str | None = None


class Stage1OnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        ssh_connector: SshConnector | None = None,
        installer: AgentInstaller | None = None,
    ) -> None:
        self._session = session
        self._ssh_connector = ssh_connector or AsyncSshConnector()
        self._installer = installer or ShellAgentInstaller()

    async def install_agent_over_ssh(self, data: SshOnboardingCreate) -> SshOnboardingResult:
        node = Node(
            name=data.name,
            host=data.host,
            agent_port=data.agent_port,
            lifecycle_status=NodeLifecycleStatus.INSTALLING_AGENT.value,
            ssh_host_key_fingerprint=None,
        )
        self._session.add(node)
        await self._session.commit()
        await self._session.refresh(node)

        connection = None
        token_issue = None
        try:
            connection = await self._ssh_connector.connect_root(
                data.host,
                data.root_password.get_secret_value(),
                data.ssh_host_key_fingerprint,
            )
            node.ssh_host_key_fingerprint = connection.host_key_fingerprint
            token_issue = await issue_bootstrap_token(self._session, node.id)
            await self._installer.install(
                connection.session,
                bootstrap_token_hash=token_issue.record.token_hash,
                bootstrap_expires_at=token_issue.record.expires_at,
            )
        except OnboardingError:
            if token_issue is not None:
                await self._cancel_token(token_issue.record)
            await self._mark_failed(node)
            raise
        except Exception as exc:
            if token_issue is not None:
                await self._cancel_token(token_issue.record)
            await self._mark_failed(node)
            raise AgentInstallError(str(exc)) from exc
        finally:
            if connection is not None:
                connection.session.close()
                await connection.session.wait_closed()

        node.lifecycle_status = NodeLifecycleStatus.BOOTSTRAP_PENDING.value
        await self._session.commit()
        await self._session.refresh(node)
        return SshOnboardingResult(
            node=node,
            raw_bootstrap_token=token_issue.raw_token,
            bootstrap_record=token_issue.record,
            warning=connection.warning,
        )

    async def _mark_failed(self, node: Node) -> None:
        node.lifecycle_status = NodeLifecycleStatus.FAILED_INSTALL.value
        await self._session.commit()
        await self._session.refresh(node)

    async def _cancel_token(self, token: NodeBootstrapToken) -> None:
        token.status = BootstrapTokenStatus.CANCELLED.value
        await self._session.commit()
        await self._session.refresh(token)
