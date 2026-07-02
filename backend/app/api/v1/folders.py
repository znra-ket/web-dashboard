from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.folder import (
    FolderCreate,
    FolderNodeAdd,
    FolderNodeCreate,
    FolderNodeRead,
    FolderRead,
    FolderScriptAdd,
    FolderScriptCreate,
    FolderScriptRead,
    FolderUpdate,
)
from app.services.folder_service import (
    add_node_to_folder,
    add_script_to_folder,
    create_folder,
    delete_folder,
    list_folders,
    read_folder,
    remove_node_from_folder,
    remove_script_from_folder,
    update_folder,
)

router = APIRouter()


@router.post("", response_model=FolderRead, status_code=status.HTTP_201_CREATED)
async def create_folder_endpoint(
    payload: FolderCreate,
    session: AsyncSession = Depends(get_session),
) -> FolderRead:
    return await create_folder(session, payload)


@router.get("", response_model=list[FolderRead])
async def list_folders_endpoint(session: AsyncSession = Depends(get_session)) -> list[FolderRead]:
    return await list_folders(session)


@router.get("/{folder_id}", response_model=FolderRead)
async def read_folder_endpoint(
    folder_id: int,
    session: AsyncSession = Depends(get_session),
) -> FolderRead:
    return await read_folder(session, folder_id)


@router.patch("/{folder_id}", response_model=FolderRead)
async def update_folder_endpoint(
    folder_id: int,
    payload: FolderUpdate,
    session: AsyncSession = Depends(get_session),
) -> FolderRead:
    return await update_folder(session, folder_id, payload)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder_endpoint(
    folder_id: int,
    preserve_bindings: bool = False,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_folder(session, folder_id, preserve_bindings=preserve_bindings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{folder_id}/nodes", response_model=FolderNodeRead, status_code=status.HTTP_201_CREATED)
async def add_node_to_folder_endpoint(
    folder_id: int,
    payload: FolderNodeAdd,
    session: AsyncSession = Depends(get_session),
) -> FolderNodeRead:
    return await add_node_to_folder(
        session,
        FolderNodeCreate(folder_id=folder_id, node_id=payload.node_id),
    )


@router.delete("/{folder_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_node_from_folder_endpoint(
    folder_id: int,
    node_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await remove_node_from_folder(session, folder_id, node_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{folder_id}/scripts", response_model=FolderScriptRead, status_code=status.HTTP_201_CREATED)
async def add_script_to_folder_endpoint(
    folder_id: int,
    payload: FolderScriptAdd,
    session: AsyncSession = Depends(get_session),
) -> FolderScriptRead:
    return await add_script_to_folder(
        session,
        FolderScriptCreate(
            folder_id=folder_id,
            script_id=payload.script_id,
            template_trigger_id=payload.trigger_id,
        ),
    )


@router.delete("/{folder_id}/scripts/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_script_from_folder_endpoint(
    folder_id: int,
    script_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await remove_script_from_folder(session, folder_id, script_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
