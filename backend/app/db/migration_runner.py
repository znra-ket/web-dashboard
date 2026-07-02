from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.migrations import MIGRATIONS, Migration

SCHEMA_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


async def ensure_schema_migrations_table(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(SCHEMA_MIGRATIONS_TABLE_SQL))


async def get_applied_migration_versions(engine: AsyncEngine) -> set[str]:
    await ensure_schema_migrations_table(engine)
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT version FROM schema_migrations"))
        return {row[0] for row in result.all()}


async def apply_migration(engine: AsyncEngine, migration: Migration) -> None:
    async with engine.begin() as connection:
        for statement in migration.statements:
            await connection.execute(text(statement))
        await connection.execute(
            text(
                """
                INSERT INTO schema_migrations (version, description)
                VALUES (:version, :description)
                """
            ),
            {"version": migration.version, "description": migration.description},
        )


async def run_migrations(engine: AsyncEngine) -> list[str]:
    applied_versions = await get_applied_migration_versions(engine)
    applied_now: list[str] = []

    for migration in MIGRATIONS:
        if migration.version in applied_versions:
            continue
        await apply_migration(engine, migration)
        applied_now.append(migration.version)

    return applied_now
