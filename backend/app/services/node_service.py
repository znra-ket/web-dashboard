from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node
from app.schemas.node import NodeCreate
from app.services.exceptions import NotFoundError


async def create_node(session: AsyncSession, data: NodeCreate) -> Node:
    node = Node(
        name=data.name,
        host=data.host,
        agent_port=data.agent_port,
        lifecycle_status=data.lifecycle_status.value,
        agent_cert_fingerprint=data.agent_cert_fingerprint,
        ssh_host_key_fingerprint=data.ssh_host_key_fingerprint,
    )
    session.add(node)
    await session.commit()
    await session.refresh(node)
    return node


async def read_node(session: AsyncSession, node_id: int) -> Node:
    node = await session.get(Node, node_id)
    if node is None:
        raise NotFoundError(f"Node {node_id} not found")
    return node


async def list_nodes(session: AsyncSession) -> list[Node]:
    result = await session.execute(select(Node).order_by(Node.id))
    return list(result.scalars().all())
