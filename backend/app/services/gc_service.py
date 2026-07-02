from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node
from app.models.node_hash_gc import NodeHashGc, NodeHashGcStatus
from app.models.node_script import NodeScript
from app.models.script import Script
from app.services.exceptions import AgentClientError, AgentScriptHashMissingError

if TYPE_CHECKING:
    from app.agent_client import AgentClient


async def desired_hashes(session: AsyncSession, node_id: int) -> set[str]:
    result = await session.execute(
        select(Script.current_hash)
        .join(NodeScript, NodeScript.script_id == Script.id)
        .where(NodeScript.node_id == node_id)
    )
    return set(result.scalars().all())


async def enqueue_hash_gc_if_not_desired(
    session: AsyncSession,
    node_id: int,
    old_hash: str,
    reason: str,
) -> NodeHashGc | None:
    if old_hash in await desired_hashes(session, node_id):
        return None

    queue_item = NodeHashGc(
        node_id=node_id,
        hash=old_hash,
        reason=reason,
        status=NodeHashGcStatus.PENDING.value,
    )
    session.add(queue_item)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return await _read_gc_item(session, node_id, old_hash)

    await session.refresh(queue_item)
    return queue_item


class HashGcService:
    def __init__(
        self,
        session: AsyncSession,
        agent_client: AgentClient,
        max_attempts: int = 3,
    ) -> None:
        self._session = session
        self._agent_client = agent_client
        self._max_attempts = max_attempts

    async def process_pending(self, limit: int = 100) -> list[NodeHashGc]:
        result = await self._session.execute(
            select(NodeHashGc)
            .where(NodeHashGc.status == NodeHashGcStatus.PENDING.value)
            .order_by(NodeHashGc.id)
            .limit(limit)
        )
        items = list(result.scalars().all())
        for item in items:
            await self.process_item(item)
        return items

    async def process_item(self, item: NodeHashGc) -> NodeHashGc:
        node = await self._session.get(Node, item.node_id)
        if node is None:
            item.status = NodeHashGcStatus.CANCELLED.value
            item.updated_at = await _current_sqlite_timestamp(self._session)
            await self._session.commit()
            await self._session.refresh(item)
            return item

        if item.hash in await desired_hashes(self._session, item.node_id):
            item.status = NodeHashGcStatus.CANCELLED.value
            item.updated_at = await _current_sqlite_timestamp(self._session)
            await self._session.commit()
            await self._session.refresh(item)
            return item

        item.last_attempt_at = await _current_sqlite_timestamp(self._session)
        try:
            await self._agent_client.delete_script_hash(node, item.hash)
        except AgentScriptHashMissingError:
            item.status = NodeHashGcStatus.DONE.value
        except AgentClientError:
            item.attempts += 1
            if item.attempts >= self._max_attempts:
                item.status = NodeHashGcStatus.FAILED.value
        else:
            item.status = NodeHashGcStatus.DONE.value

        item.updated_at = await _current_sqlite_timestamp(self._session)
        await self._session.commit()
        await self._session.refresh(item)
        return item


async def _read_gc_item(session: AsyncSession, node_id: int, hash_value: str) -> NodeHashGc | None:
    result = await session.execute(
        select(NodeHashGc).where(
            NodeHashGc.node_id == node_id,
            NodeHashGc.hash == hash_value,
        )
    )
    return result.scalar_one_or_none()


async def _current_sqlite_timestamp(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT datetime('now')"))
    return str(result.scalar_one())
