from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeLifecycleStatus
from app.services.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from app.agent_client import AgentClient


OFFLINE_DELETE_WARNING = (
    "Node was deleted only from the dashboard. The VPS may still contain web-xray-agent, "
    "systemd unit, private key, certificate, trust anchor, scripts, workdir, and logs."
)


@dataclass(frozen=True)
class NodeDeletionResult:
    node_id: int
    deleted: bool
    warnings: tuple[str, ...] = ()


class NodeDeletionService:
    def __init__(self, session: AsyncSession, agent_client: AgentClient) -> None:
        self._session = session
        self._agent_client = agent_client

    async def delete_online(self, node_id: int) -> NodeDeletionResult:
        node = await self._set_status(node_id, NodeLifecycleStatus.UNPAIRING)
        await self._agent_client.unpair(node)
        await self._delete_local(node)
        return NodeDeletionResult(node_id=node_id, deleted=True)

    async def delete_offline(self, node_id: int) -> NodeDeletionResult:
        node = await self._read_node(node_id)
        await self._delete_local(node)
        return NodeDeletionResult(
            node_id=node_id,
            deleted=True,
            warnings=(OFFLINE_DELETE_WARNING,),
        )

    async def uninstall_online(self, node_id: int) -> NodeDeletionResult:
        node = await self._set_status(node_id, NodeLifecycleStatus.UNINSTALLING)
        await self._agent_client.uninstall(node)
        await self._delete_local(node)
        return NodeDeletionResult(node_id=node_id, deleted=True)

    async def uninstall_offline(self, node_id: int) -> NodeDeletionResult:
        await self._read_node(node_id)
        raise ValidationError("Full node cleanup requires an online node")

    async def _set_status(self, node_id: int, status: NodeLifecycleStatus) -> Node:
        node = await self._read_node(node_id)
        node.lifecycle_status = status.value
        await self._session.commit()
        await self._session.refresh(node)
        return node

    async def _read_node(self, node_id: int) -> Node:
        node = await self._session.get(Node, node_id)
        if node is None:
            raise NotFoundError(f"Node {node_id} not found")
        return node

    async def _delete_local(self, node: Node) -> None:
        await self._session.delete(node)
        await self._session.commit()
