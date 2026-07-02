import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node import NodeLifecycleStatus
from app.schemas.folder import FolderCreate, FolderNodeCreate, FolderScriptCreate, NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate
from app.services.exceptions import ConflictError
from app.services.folder_service import (
    add_node_to_folder,
    add_script_to_folder,
    create_folder,
    create_node_script,
)
from app.services.node_service import create_node
from app.services.script_service import create_script
from app.services.trigger_service import create_on_startup_trigger, create_schedule_trigger


class FolderLinkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_create_folder_folder_node_folder_script_and_manual_node_script(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.ACTIVE,
                ),
            )
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_id = node.id
            script_id = script.id
            folder_id = folder.id

            folder_node = await add_node_to_folder(
                session,
                FolderNodeCreate(folder_id=folder_id, node_id=node_id),
            )
            folder_script = await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_id),
            )
            node_script = await create_node_script(
                session,
                NodeScriptCreate(node_id=node_id, script_id=script_id),
            )

        self.assertEqual((folder_node.folder_id, folder_node.node_id), (folder_id, node_id))
        self.assertEqual((folder_script.folder_id, folder_script.script_id), (folder_id, script_id))
        self.assertEqual(node_script.folder_id, None)
        self.assertEqual(node_script.trigger_id, None)

    async def test_folder_node_and_folder_script_duplicates_are_rejected(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(name="node-1", host="203.0.113.10"),
            )
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_id = node.id
            script_id = script.id
            folder_id = folder.id

            await add_node_to_folder(session, FolderNodeCreate(folder_id=folder_id, node_id=node_id))
            await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_id),
            )

            with self.assertRaises(ConflictError):
                await add_node_to_folder(
                    session,
                    FolderNodeCreate(folder_id=folder_id, node_id=node_id),
                )

            with self.assertRaises(ConflictError):
                await add_script_to_folder(
                    session,
                    FolderScriptCreate(folder_id=folder_id, script_id=script_id),
                )

    async def test_node_script_partial_unique_indexes(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
            folder_a = await create_folder(session, FolderCreate(name="ops-a"))
            folder_b = await create_folder(session, FolderCreate(name="ops-b"))
            schedule_trigger = await create_schedule_trigger(session, interval_seconds=60)
            startup_trigger = await create_on_startup_trigger(session)
            node_id = node.id
            script_id = script.id
            folder_a_id = folder_a.id
            folder_b_id = folder_b.id
            schedule_trigger_id = schedule_trigger.id
            startup_trigger_id = startup_trigger.id

            await create_node_script(session, NodeScriptCreate(node_id=node_id, script_id=script_id))
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node_id, script_id=script_id, trigger_id=schedule_trigger_id),
            )
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node_id, script_id=script_id, trigger_id=startup_trigger_id),
            )
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node_id, script_id=script_id, folder_id=folder_a_id),
            )
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node_id, script_id=script_id, folder_id=folder_b_id),
            )

            with self.assertRaises(ConflictError):
                await create_node_script(
                    session,
                    NodeScriptCreate(node_id=node_id, script_id=script_id),
                )

            with self.assertRaises(ConflictError):
                await create_node_script(
                    session,
                    NodeScriptCreate(
                        node_id=node_id,
                        script_id=script_id,
                        trigger_id=schedule_trigger_id,
                    ),
                )

            with self.assertRaises(ConflictError):
                await create_node_script(
                    session,
                    NodeScriptCreate(node_id=node_id, script_id=script_id, folder_id=folder_a_id),
                )
