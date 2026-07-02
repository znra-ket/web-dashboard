import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.migration_runner import run_migrations
from app.db.migrations import MIGRATIONS


class MigrationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_migrations_apply_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")

            try:
                first_run = await run_migrations(engine)
                second_run = await run_migrations(engine)

                async with engine.connect() as connection:
                    result = await connection.execute(
                        text("SELECT version FROM schema_migrations ORDER BY version")
                    )
                    applied_versions = [row[0] for row in result.all()]

                    node_table = await connection.execute(
                        text(
                            """
                            SELECT name FROM sqlite_master
                            WHERE type = 'table' AND name = 'node'
                            """
                        )
                    )

                self.assertEqual(first_run, [migration.version for migration in MIGRATIONS])
                self.assertEqual(second_run, [])
                self.assertEqual(applied_versions, [migration.version for migration in MIGRATIONS])
                self.assertEqual(node_table.scalar_one(), "node")
            finally:
                await engine.dispose()
