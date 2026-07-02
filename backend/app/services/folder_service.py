from sqlalchemy import delete, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.folder import Folder, FolderNode, FolderScript
from app.models.node_script import NodeScript
from app.schemas.folder import FolderCreate, FolderNodeCreate, FolderScriptCreate, NodeScriptCreate
from app.services.exceptions import ConflictError, NotFoundError
from app.services.trigger_service import clone_trigger


async def create_folder(session: AsyncSession, data: FolderCreate) -> Folder:
    folder = Folder(name=data.name)
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return folder


async def delete_folder(session: AsyncSession, folder_id: int, preserve_bindings: bool) -> None:
    folder = await session.get(Folder, folder_id)
    if folder is None:
        raise NotFoundError(f"Folder {folder_id} not found")

    try:
        if preserve_bindings:
            await _convert_folder_bindings_to_manual(session, folder_id)
        else:
            await session.execute(delete(NodeScript).where(NodeScript.folder_id == folder_id))

        await session.delete(folder)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(f"Could not delete folder {folder_id}") from exc


async def add_node_to_folder(
    session: AsyncSession,
    folder_id: int | FolderNodeCreate,
    node_id: int | None = None,
) -> FolderNode:
    data = _coerce_folder_node_create(folder_id, node_id)
    folder_node = FolderNode(folder_id=data.folder_id, node_id=data.node_id)
    session.add(folder_node)
    try:
        await session.flush()
        await _clone_folder_script_triggers_for_node(session, data.folder_id, data.node_id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("Folder-node link already exists") from exc

    await session.refresh(folder_node)
    return folder_node


async def add_script_to_folder(
    session: AsyncSession,
    folder_id: int | FolderScriptCreate,
    script_id: int | None = None,
    template_trigger_id: int | None = None,
) -> FolderScript:
    data = _coerce_folder_script_create(folder_id, script_id, template_trigger_id)
    await _ensure_trigger_is_unowned(session, data.trigger_id)
    folder_script = FolderScript(
        folder_id=data.folder_id,
        script_id=data.script_id,
        trigger_id=data.trigger_id,
    )
    session.add(folder_script)
    try:
        await session.flush()
        await _clone_folder_script_triggers_for_script(session, data.folder_id, data.script_id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("Folder-script link already exists") from exc

    await session.refresh(folder_script)
    return folder_script


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


def _coerce_folder_node_create(
    folder_id: int | FolderNodeCreate,
    node_id: int | None,
) -> FolderNodeCreate:
    if isinstance(folder_id, FolderNodeCreate):
        return folder_id
    if node_id is None:
        raise TypeError("node_id is required")
    return FolderNodeCreate(folder_id=folder_id, node_id=node_id)


def _coerce_folder_script_create(
    folder_id: int | FolderScriptCreate,
    script_id: int | None,
    template_trigger_id: int | None,
) -> FolderScriptCreate:
    if isinstance(folder_id, FolderScriptCreate):
        return folder_id
    if script_id is None:
        raise TypeError("script_id is required")
    return FolderScriptCreate(
        folder_id=folder_id,
        script_id=script_id,
        template_trigger_id=template_trigger_id,
    )


async def _clone_folder_script_triggers_for_node(
    session: AsyncSession,
    folder_id: int,
    node_id: int,
) -> None:
    result = await session.execute(
        select(NodeScript, FolderScript.trigger_id)
        .join(
            FolderScript,
            (FolderScript.folder_id == NodeScript.folder_id)
            & (FolderScript.script_id == NodeScript.script_id),
        )
        .where(
            NodeScript.folder_id == folder_id,
            NodeScript.node_id == node_id,
            NodeScript.trigger_id.is_(None),
            FolderScript.trigger_id.is_not(None),
        )
    )
    for node_script, template_trigger_id in result.all():
        cloned = await clone_trigger(session, template_trigger_id)
        node_script.trigger_id = cloned.id


async def _clone_folder_script_triggers_for_script(
    session: AsyncSession,
    folder_id: int,
    script_id: int,
) -> None:
    result = await session.execute(
        select(NodeScript, FolderScript.trigger_id)
        .join(
            FolderScript,
            (FolderScript.folder_id == NodeScript.folder_id)
            & (FolderScript.script_id == NodeScript.script_id),
        )
        .where(
            NodeScript.folder_id == folder_id,
            NodeScript.script_id == script_id,
            NodeScript.trigger_id.is_(None),
            FolderScript.trigger_id.is_not(None),
        )
    )
    for node_script, template_trigger_id in result.all():
        cloned = await clone_trigger(session, template_trigger_id)
        node_script.trigger_id = cloned.id


async def _convert_folder_bindings_to_manual(session: AsyncSession, folder_id: int) -> None:
    result = await session.execute(
        select(NodeScript)
        .where(NodeScript.folder_id == folder_id)
        .order_by(NodeScript.id)
    )
    folder_links = list(result.scalars().all())

    for folder_link in folder_links:
        manual_duplicate_id = await _find_manual_duplicate_id(session, folder_link)
        if manual_duplicate_id is None:
            folder_link.folder_id = None
        else:
            await session.delete(folder_link)

    await session.flush()


async def _find_manual_duplicate_id(
    session: AsyncSession,
    folder_link: NodeScript,
) -> int | None:
    query = select(NodeScript.id).where(
        NodeScript.node_id == folder_link.node_id,
        NodeScript.script_id == folder_link.script_id,
        NodeScript.folder_id.is_(None),
    )
    if folder_link.trigger_id is None:
        query = query.where(NodeScript.trigger_id.is_(None))
    else:
        query = query.where(NodeScript.trigger_id == folder_link.trigger_id)

    return await session.scalar(query.limit(1))
