from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.folder import Folder, FolderNode, FolderScript
from app.models.node_script import NodeScript
from app.schemas.folder import FolderCreate, FolderNodeCreate, FolderScriptCreate, NodeScriptCreate
from app.services.exceptions import ConflictError


async def create_folder(session: AsyncSession, data: FolderCreate) -> Folder:
    folder = Folder(name=data.name)
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return folder


async def add_node_to_folder(session: AsyncSession, data: FolderNodeCreate) -> FolderNode:
    folder_node = FolderNode(folder_id=data.folder_id, node_id=data.node_id)
    session.add(folder_node)
    return await _commit_or_conflict(session, folder_node, "Folder-node link already exists")


async def add_script_to_folder(session: AsyncSession, data: FolderScriptCreate) -> FolderScript:
    await _ensure_trigger_is_unowned(session, data.trigger_id)
    folder_script = FolderScript(
        folder_id=data.folder_id,
        script_id=data.script_id,
        trigger_id=data.trigger_id,
    )
    session.add(folder_script)
    return await _commit_or_conflict(session, folder_script, "Folder-script link already exists")


async def create_node_script(session: AsyncSession, data: NodeScriptCreate) -> NodeScript:
    await _ensure_trigger_is_unowned(session, data.trigger_id)
    node_script = NodeScript(
        node_id=data.node_id,
        script_id=data.script_id,
        folder_id=data.folder_id,
        trigger_id=data.trigger_id,
    )
    session.add(node_script)
    return await _commit_or_conflict(session, node_script, "Node-script link already exists")


async def _commit_or_conflict(
    session: AsyncSession,
    instance: FolderNode | FolderScript | NodeScript,
    message: str,
) -> FolderNode | FolderScript | NodeScript:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(message) from exc

    await session.refresh(instance)
    return instance


async def _ensure_trigger_is_unowned(session: AsyncSession, trigger_id: int | None) -> None:
    if trigger_id is None:
        return

    node_script_owner = await session.scalar(
        select(exists().where(NodeScript.trigger_id == trigger_id))
    )
    folder_script_owner = await session.scalar(
        select(exists().where(FolderScript.trigger_id == trigger_id))
    )

    if node_script_owner or folder_script_owner:
        raise ConflictError(f"Trigger {trigger_id} is already attached to a link")
