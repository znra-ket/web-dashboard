from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.migration_runner import run_migrations
from app.db.session import dispose_engine, get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    engine = get_engine(settings.database_url)
    await run_migrations(engine)
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="web-xray-dashboard", lifespan=lifespan)
    app.state.settings = settings or get_settings()
    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
