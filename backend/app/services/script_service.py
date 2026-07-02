from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.script import Script
from app.schemas.script import ScriptCreate, ScriptUpdateContent
from app.services.exceptions import ConflictError, NotFoundError
from app.services.hash import calculate_script_hash


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
) -> Script:
    script = await read_script(session, script_id)
    script.content = data.content
    script.current_hash = calculate_script_hash(data.content)
    script.updated_at = await _current_sqlite_timestamp(session)
    await session.commit()
    await session.refresh(script)
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
