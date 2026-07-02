from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node_hash_gc import NodeHashGc, NodeHashGcStatus
from app.models.node_script import NodeScript
from app.models.script import Script


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


async def _read_gc_item(session: AsyncSession, node_id: int, hash_value: str) -> NodeHashGc | None:
    result = await session.execute(
        select(NodeHashGc).where(
            NodeHashGc.node_id == node_id,
            NodeHashGc.hash == hash_value,
        )
    )
    return result.scalar_one_or_none()
