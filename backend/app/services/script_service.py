from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node import Node, NodeLifecycleStatus
from app.models.node_script import NodeScript
from app.models.script import Script
from app.schemas.script import ScriptCreate, ScriptUpdateContent
from app.services.exceptions import AgentClientError, ConflictError, NotFoundError
from app.services.gc_service import enqueue_hash_gc_if_not_desired
from app.services.hash import calculate_script_hash

if TYPE_CHECKING:
    from app.agent_client import AgentClient


async def create_script(session: AsyncSession, data: ScriptCreate) -> Script:
    script = Script(
        name=data.name,
        content=data.content,
        current_hash=calculate_script_hash(data.content),
    )
    session.add(script)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(f"Script name already exists: {data.name}") from exc

    await session.refresh(script)
    return script


async def update_script_content(
    session: AsyncSession,
    script_id: int,
    data: ScriptUpdateContent,
    agent_client: AgentClient | None = None,
) -> Script:
    script = await read_script(session, script_id)
    old_hash = script.current_hash
    affected_nodes = await _affected_nodes_for_script(session, script_id)
    script.content = data.content
    script.current_hash = calculate_script_hash(data.content)
    script.updated_at = await _current_sqlite_timestamp(session)
    await session.commit()
    await session.refresh(script)

    if old_hash != script.current_hash:
        await _best_effort_upload_to_online_nodes(agent_client, affected_nodes, script.content)
        for node in affected_nodes:
            await enqueue_hash_gc_if_not_desired(
                session,
                node.id,
                old_hash,
                reason="script_updated",
            )

    return script


async def read_script(session: AsyncSession, script_id: int) -> Script:
    script = await session.get(Script, script_id)
    if script is None:
        raise NotFoundError(f"Script {script_id} not found")
    return script


async def list_scripts(session: AsyncSession) -> list[Script]:
    result = await session.execute(select(Script).order_by(Script.id))
    return list(result.scalars().all())


async def _current_sqlite_timestamp(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT datetime('now')"))
    return str(result.scalar_one())


async def _affected_nodes_for_script(session: AsyncSession, script_id: int) -> list[Node]:
    result = await session.execute(
        select(Node)
        .join(NodeScript, NodeScript.node_id == Node.id)
        .where(NodeScript.script_id == script_id)
        .distinct()
        .order_by(Node.id)
    )
    return list(result.scalars().all())


async def _best_effort_upload_to_online_nodes(
    agent_client: AgentClient | None,
    nodes: list[Node],
    script_content: str,
) -> None:
    if agent_client is None:
        return

    for node in nodes:
        if node.lifecycle_status != NodeLifecycleStatus.ACTIVE.value:
            continue
        try:
            await agent_client.upload_script(node, script_content)
        except AgentClientError:
            continue
