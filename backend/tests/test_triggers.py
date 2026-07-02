import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.trigger import Trigger, TriggerOnStartup, TriggerSchedule
from app.schemas.folder import FolderCreate, FolderScriptCreate, NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate
from app.services.exceptions import ConflictError, ValidationError
from app.services.folder_service import add_script_to_folder, create_folder, create_node_script
from app.services.node_service import create_node
from app.services.script_service import create_script
from app.services.trigger_service import create_on_startup_trigger, create_schedule_trigger


class TriggerSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_schedule_trigger_creates_schedule_config(self) -> None:
        async with self.session_maker() as session:
            trigger = await create_schedule_trigger(session, interval_seconds=21600)
            schedule = await session.get(TriggerSchedule, trigger.id)
            startup = await session.get(TriggerOnStartup, trigger.id)

        self.assertEqual(trigger.type, "schedule")
        self.assertIsNotNone(schedule)
        self.assertEqual(schedule.interval_seconds, 21600)
        self.assertIsNone(startup)

    async def test_on_startup_trigger_creates_on_startup_config(self) -> None:
        async with self.session_maker() as session:
            trigger = await create_on_startup_trigger(session)
            startup = await session.get(TriggerOnStartup, trigger.id)
            schedule = await session.get(TriggerSchedule, trigger.id)

        self.assertEqual(trigger.type, "on_startup")
        self.assertIsNotNone(startup)
        self.assertIsNone(schedule)

    async def test_schedule_interval_must_be_positive(self) -> None:
        async with self.session_maker() as session:
            with self.assertRaises(ValidationError):
                await create_schedule_trigger(session, interval_seconds=0)

    async def test_trigger_delete_is_restricted_when_used_by_node_script(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
            trigger = await create_schedule_trigger(session, interval_seconds=60)
            trigger_id = trigger.id

            await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id, trigger_id=trigger_id),
            )

            with self.assertRaises(IntegrityError):
                await session.execute(delete(Trigger).where(Trigger.id == trigger_id))
                await session.commit()

            await session.rollback()

            loaded = await session.get(Trigger, trigger_id)
            self.assertIsNotNone(loaded)

    async def test_trigger_delete_is_restricted_when_used_by_folder_script(self) -> None:
        async with self.session_maker() as session:
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            trigger = await create_on_startup_trigger(session)
            trigger_id = trigger.id

            await add_script_to_folder(
                session,
                FolderScriptCreate(
                    folder_id=folder.id,
                    script_id=script.id,
                    trigger_id=trigger_id,
                ),
            )

            with self.assertRaises(IntegrityError):
                await session.execute(delete(Trigger).where(Trigger.id == trigger_id))
                await session.commit()

            await session.rollback()

            loaded = await session.get(Trigger, trigger_id)
            self.assertIsNotNone(loaded)

    async def test_trigger_id_cannot_be_reused_between_links(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            trigger = await create_schedule_trigger(session, interval_seconds=60)
            trigger_id = trigger.id

            await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id, trigger_id=trigger_id),
            )

            with self.assertRaises(ConflictError):
                await add_script_to_folder(
                    session,
                    FolderScriptCreate(
                        folder_id=folder.id,
                        script_id=script.id,
                        trigger_id=trigger_id,
                    ),
                )

    async def test_manual_only_link_has_null_trigger_id(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))

            link = await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id),
            )
            trigger_types = await session.execute(select(Trigger.type))

        self.assertIsNone(link.trigger_id)
        self.assertNotIn("manual", [row[0] for row in trigger_types.all()])
