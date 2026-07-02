from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None
_engine_url: str | None = None


def get_engine(database_url: str | None = None) -> AsyncEngine:
    global _engine, _engine_url, _session_maker
    resolved_url = database_url or get_settings().database_url
    if _engine is None or _engine_url != resolved_url:
        _engine = create_async_engine(resolved_url, future=True)
        _engine_url = resolved_url
        _session_maker = None
    return _engine


def get_session_maker(database_url: str | None = None) -> async_sessionmaker[AsyncSession]:
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            bind=get_engine(database_url),
            expire_on_commit=False,
        )
    return _session_maker


async def get_session() -> AsyncIterator[AsyncSession]:
    async_session = get_session_maker()
    async with async_session() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _engine_url, _session_maker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _engine_url = None
    _session_maker = None
