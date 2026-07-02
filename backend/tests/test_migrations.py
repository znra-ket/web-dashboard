import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from app.db.migration_runner import run_migrations
from app.db.migrations import MIGRATIONS
from app.db.session import create_database_engine


class MigrationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_migrations_apply_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")

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
                    script_table = await connection.execute(
                        text(
                            """
                            SELECT name FROM sqlite_master
                            WHERE type = 'table' AND name = 'script'
                            """
                        )
                    )
                    node_columns_result = await connection.execute(text("PRAGMA table_info(node)"))
                    node_columns = {row[1] for row in node_columns_result.all()}
                    tables_result = await connection.execute(
                        text("SELECT name FROM sqlite_master WHERE type = 'table'")
                    )
                    tables = {row[0] for row in tables_result.all()}
                    node_script_indexes_result = await connection.execute(
                        text("PRAGMA index_list(node_script)")
                    )
                    node_script_indexes = {row[1] for row in node_script_indexes_result.all()}
                    node_script_fk_result = await connection.execute(
                        text("PRAGMA foreign_key_list(node_script)")
                    )
                    node_script_fk_tables = {row[2] for row in node_script_fk_result.all()}
                    folder_script_fk_result = await connection.execute(
                        text("PRAGMA foreign_key_list(folder_script)")
                    )
                    folder_script_fk_tables = {row[2] for row in folder_script_fk_result.all()}

                self.assertEqual(first_run, [migration.version for migration in MIGRATIONS])
                self.assertEqual(second_run, [])
                self.assertEqual(applied_versions, [migration.version for migration in MIGRATIONS])
                self.assertEqual(node_table.scalar_one(), "node")
                self.assertEqual(script_table.scalar_one(), "script")
                self.assertTrue(
                    {
                        "folder",
                        "folder_node",
                        "folder_script",
                        "node_script",
                        "trigger",
                        "trigger_schedule",
                        "trigger_on_startup",
                    }.issubset(tables)
                )
                self.assertIn("trigger", node_script_fk_tables)
                self.assertIn("trigger", folder_script_fk_tables)
                self.assertTrue(
                    {
                        "ux_node_script_folder",
                        "ux_node_script_manual_no_trigger",
                        "ux_node_script_manual_with_trigger",
                    }.issubset(node_script_indexes)
                )
                self.assertTrue(
                    {
                        "id",
                        "name",
                        "host",
                        "agent_port",
                        "lifecycle_status",
                        "agent_cert_fingerprint",
                        "ssh_host_key_fingerprint",
                        "created_at",
                        "updated_at",
                    }.issubset(node_columns)
                )
            finally:
                await engine.dispose()
