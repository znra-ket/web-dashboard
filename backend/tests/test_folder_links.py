import tempfile
import unittest
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.folder import Folder, FolderNode, FolderScript
from app.models.node import NodeLifecycleStatus
from app.models.node_script import NodeScript
from app.models.trigger import Trigger, TriggerSchedule
from app.schemas.folder import FolderCreate, FolderNodeCreate, FolderScriptCreate, NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate
from app.services.exceptions import ConflictError
from app.services.folder_service import (
    add_node_to_folder,
    add_script_to_folder,
    create_folder,
    create_node_script,
    delete_folder,
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

    async def test_adding_node_to_folder_materializes_existing_folder_scripts(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script_a = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            script_b = await create_script(session, ScriptCreate(name="script-b", content="echo b"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_id = node.id
            script_a_id = script_a.id
            script_b_id = script_b.id
            folder_id = folder.id

            await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_a_id),
            )
            await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_b_id),
            )
            await add_node_to_folder(session, FolderNodeCreate(folder_id=folder_id, node_id=node_id))

            links = await _folder_node_script_rows(session, folder_id)

        self.assertEqual(
            {(link.node_id, link.script_id, link.folder_id) for link in links},
            {
                (node_id, script_a_id, folder_id),
                (node_id, script_b_id, folder_id),
            },
        )

    async def test_adding_script_to_folder_materializes_existing_folder_nodes(self) -> None:
        async with self.session_maker() as session:
            node_a = await create_node(session, NodeCreate(name="node-a", host="203.0.113.10"))
            node_b = await create_node(session, NodeCreate(name="node-b", host="203.0.113.11"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_a_id = node_a.id
            node_b_id = node_b.id
            script_id = script.id
            folder_id = folder.id

            await add_node_to_folder(session, FolderNodeCreate(folder_id=folder_id, node_id=node_a_id))
            await add_node_to_folder(session, FolderNodeCreate(folder_id=folder_id, node_id=node_b_id))
            await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_id),
            )

            links = await _folder_node_script_rows(session, folder_id)

        self.assertEqual(
            {(link.node_id, link.script_id, link.folder_id) for link in links},
            {
                (node_a_id, script_id, folder_id),
                (node_b_id, script_id, folder_id),
            },
        )

    async def test_deleting_folder_node_revokes_that_nodes_folder_links(self) -> None:
        async with self.session_maker() as session:
            node_a = await create_node(session, NodeCreate(name="node-a", host="203.0.113.10"))
            node_b = await create_node(session, NodeCreate(name="node-b", host="203.0.113.11"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_a_id = node_a.id
            node_b_id = node_b.id
            script_id = script.id
            folder_id = folder.id

            await add_node_to_folder(session, FolderNodeCreate(folder_id=folder_id, node_id=node_a_id))
            await add_node_to_folder(session, FolderNodeCreate(folder_id=folder_id, node_id=node_b_id))
            await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_id),
            )

            await session.execute(
                delete(FolderNode).where(
                    FolderNode.folder_id == folder_id,
                    FolderNode.node_id == node_a_id,
                )
            )
            await session.commit()

            links = await _folder_node_script_rows(session, folder_id)

        self.assertEqual(
            {(link.node_id, link.script_id, link.folder_id) for link in links},
            {(node_b_id, script_id, folder_id)},
        )

    async def test_deleting_folder_script_revokes_that_scripts_folder_links(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script_a = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            script_b = await create_script(session, ScriptCreate(name="script-b", content="echo b"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_id = node.id
            script_a_id = script_a.id
            script_b_id = script_b.id
            folder_id = folder.id

            await add_node_to_folder(session, FolderNodeCreate(folder_id=folder_id, node_id=node_id))
            await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_a_id),
            )
            await add_script_to_folder(
                session,
                FolderScriptCreate(folder_id=folder_id, script_id=script_b_id),
            )

            await session.execute(
                delete(FolderScript).where(
                    FolderScript.folder_id == folder_id,
                    FolderScript.script_id == script_a_id,
                )
            )
            await session.commit()

            links = await _folder_node_script_rows(session, folder_id)

        self.assertEqual(
            {(link.node_id, link.script_id, link.folder_id) for link in links},
            {(node_id, script_b_id, folder_id)},
        )

    async def test_add_script_to_folder_clones_template_trigger_for_each_existing_node(self) -> None:
        async with self.session_maker() as session:
            node_a = await create_node(session, NodeCreate(name="node-a", host="203.0.113.10"))
            node_b = await create_node(session, NodeCreate(name="node-b", host="203.0.113.11"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            template = await create_schedule_trigger(session, interval_seconds=300)
            node_a_id = node_a.id
            node_b_id = node_b.id
            script_id = script.id
            folder_id = folder.id
            template_trigger_id = template.id

            await add_node_to_folder(session, folder_id, node_a_id)
            await add_node_to_folder(session, folder_id, node_b_id)
            await add_script_to_folder(
                session,
                folder_id,
                script_id,
                template_trigger_id=template_trigger_id,
            )

            links = await _folder_node_script_rows(session, folder_id)
            schedules = {
                link.trigger_id: await session.get(TriggerSchedule, link.trigger_id)
                for link in links
            }

        materialized_trigger_ids = {link.trigger_id for link in links}
        self.assertEqual({link.node_id for link in links}, {node_a_id, node_b_id})
        self.assertEqual(len(materialized_trigger_ids), 2)
        self.assertNotIn(template_trigger_id, materialized_trigger_ids)
        self.assertTrue(all(schedule.interval_seconds == 300 for schedule in schedules.values()))

    async def test_add_node_to_folder_clones_existing_folder_script_template_trigger(self) -> None:
        async with self.session_maker() as session:
            node_a = await create_node(session, NodeCreate(name="node-a", host="203.0.113.10"))
            node_b = await create_node(session, NodeCreate(name="node-b", host="203.0.113.11"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            template = await create_schedule_trigger(session, interval_seconds=120)
            node_a_id = node_a.id
            node_b_id = node_b.id
            script_id = script.id
            folder_id = folder.id
            template_trigger_id = template.id

            await add_script_to_folder(
                session,
                folder_id,
                script_id,
                template_trigger_id=template_trigger_id,
            )
            await add_node_to_folder(session, folder_id, node_a_id)
            await add_node_to_folder(session, folder_id, node_b_id)

            links = await _folder_node_script_rows(session, folder_id)

        materialized_trigger_ids = {link.trigger_id for link in links}
        self.assertEqual({link.node_id for link in links}, {node_a_id, node_b_id})
        self.assertEqual(len(materialized_trigger_ids), 2)
        self.assertNotIn(template_trigger_id, materialized_trigger_ids)

    async def test_updating_one_materialized_trigger_copy_does_not_change_others(self) -> None:
        async with self.session_maker() as session:
            node_a = await create_node(session, NodeCreate(name="node-a", host="203.0.113.10"))
            node_b = await create_node(session, NodeCreate(name="node-b", host="203.0.113.11"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            template = await create_schedule_trigger(session, interval_seconds=300)
            folder_id = folder.id
            template_trigger_id = template.id

            await add_node_to_folder(session, folder_id, node_a.id)
            await add_node_to_folder(session, folder_id, node_b.id)
            await add_script_to_folder(
                session,
                folder_id,
                script.id,
                template_trigger_id=template_trigger_id,
            )

            links = await _folder_node_script_rows(session, folder_id)
            first_trigger_id = links[0].trigger_id
            second_trigger_id = links[1].trigger_id

            await session.execute(
                update(TriggerSchedule)
                .where(TriggerSchedule.trigger_id == first_trigger_id)
                .values(interval_seconds=900)
            )
            await session.commit()

            first_schedule = await session.get(TriggerSchedule, first_trigger_id)
            second_schedule = await session.get(TriggerSchedule, second_trigger_id)
            template_schedule = await session.get(TriggerSchedule, template_trigger_id)

        self.assertEqual(first_schedule.interval_seconds, 900)
        self.assertEqual(second_schedule.interval_seconds, 300)
        self.assertEqual(template_schedule.interval_seconds, 300)

    async def test_orphan_node_script_trigger_is_deleted_after_delete(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            trigger = await create_schedule_trigger(session, interval_seconds=300)
            trigger_id = trigger.id
            link = await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id, trigger_id=trigger_id),
            )

            await session.execute(delete(NodeScript).where(NodeScript.id == link.id))
            await session.commit()

            removed_trigger = await session.scalar(select(Trigger.id).where(Trigger.id == trigger_id))
            removed_schedule = await session.scalar(
                select(TriggerSchedule.trigger_id).where(TriggerSchedule.trigger_id == trigger_id)
            )

        self.assertIsNone(removed_trigger)
        self.assertIsNone(removed_schedule)

    async def test_orphan_node_script_trigger_is_deleted_after_update(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            old_trigger = await create_schedule_trigger(session, interval_seconds=300)
            new_trigger = await create_schedule_trigger(session, interval_seconds=600)
            old_trigger_id = old_trigger.id
            new_trigger_id = new_trigger.id
            link = await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id, trigger_id=old_trigger_id),
            )

            await session.execute(
                update(NodeScript)
                .where(NodeScript.id == link.id)
                .values(trigger_id=new_trigger_id)
            )
            await session.commit()

            removed_old_trigger = await session.scalar(
                select(Trigger.id).where(Trigger.id == old_trigger_id)
            )
            loaded_new_trigger = await session.scalar(
                select(Trigger.id).where(Trigger.id == new_trigger_id)
            )

        self.assertIsNone(removed_old_trigger)
        self.assertEqual(loaded_new_trigger, new_trigger_id)

    async def test_orphan_folder_script_trigger_is_deleted_after_update(self) -> None:
        async with self.session_maker() as session:
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            template = await create_schedule_trigger(session, interval_seconds=300)
            template_trigger_id = template.id
            folder_script = await add_script_to_folder(
                session,
                folder.id,
                script.id,
                template_trigger_id=template_trigger_id,
            )

            await session.execute(
                update(FolderScript)
                .where(FolderScript.id == folder_script.id)
                .values(trigger_id=None)
            )
            await session.commit()

            removed_trigger = await session.scalar(
                select(Trigger.id).where(Trigger.id == template_trigger_id)
            )
            removed_schedule = await session.scalar(
                select(TriggerSchedule.trigger_id).where(
                    TriggerSchedule.trigger_id == template_trigger_id
                )
            )

        self.assertIsNone(removed_trigger)
        self.assertIsNone(removed_schedule)

    async def test_orphan_folder_script_trigger_is_deleted_after_delete(self) -> None:
        async with self.session_maker() as session:
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            template = await create_schedule_trigger(session, interval_seconds=300)
            template_trigger_id = template.id
            folder_script = await add_script_to_folder(
                session,
                folder.id,
                script.id,
                template_trigger_id=template_trigger_id,
            )

            await session.execute(delete(FolderScript).where(FolderScript.id == folder_script.id))
            await session.commit()

            removed_trigger = await session.scalar(
                select(Trigger.id).where(Trigger.id == template_trigger_id)
            )
            removed_schedule = await session.scalar(
                select(TriggerSchedule.trigger_id).where(
                    TriggerSchedule.trigger_id == template_trigger_id
                )
            )

        self.assertIsNone(removed_trigger)
        self.assertIsNone(removed_schedule)

    async def test_delete_folder_preserves_bindings_as_manual_links(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_id = node.id
            script_id = script.id
            folder_id = folder.id

            await add_node_to_folder(session, folder_id, node_id)
            await add_script_to_folder(session, folder_id, script_id)

            await delete_folder(session, folder_id, preserve_bindings=True)

            folder_after_delete = await session.get(Folder, folder_id)
            links = await _manual_node_script_rows(session)

        self.assertIsNone(folder_after_delete)
        self.assertEqual(
            [(link.node_id, link.script_id, link.folder_id, link.trigger_id) for link in links],
            [(node_id, script_id, None, None)],
        )

    async def test_delete_folder_without_preserving_removes_folder_links(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            folder_id = folder.id

            await add_node_to_folder(session, folder_id, node.id)
            await add_script_to_folder(session, folder_id, script.id)

            await delete_folder(session, folder_id, preserve_bindings=False)

            folder_after_delete = await session.get(Folder, folder_id)
            links = await _all_node_script_rows(session)

        self.assertIsNone(folder_after_delete)
        self.assertEqual(links, [])

    async def test_delete_folder_preserve_removes_duplicate_folder_link(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            node_id = node.id
            script_id = script.id
            folder_id = folder.id

            manual_link = await create_node_script(
                session,
                NodeScriptCreate(node_id=node_id, script_id=script_id),
            )
            manual_link_id = manual_link.id
            await add_node_to_folder(session, folder_id, node_id)
            await add_script_to_folder(session, folder_id, script_id)

            await delete_folder(session, folder_id, preserve_bindings=True)

            links = await _all_node_script_rows(session)

        self.assertEqual([link.id for link in links], [manual_link_id])
        self.assertEqual(links[0].folder_id, None)
        self.assertEqual(links[0].trigger_id, None)

    async def test_delete_folder_without_preserving_cleans_orphan_triggers(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            folder = await create_folder(session, FolderCreate(name="ops"))
            template = await create_schedule_trigger(session, interval_seconds=300)
            folder_id = folder.id
            template_trigger_id = template.id

            await add_node_to_folder(session, folder_id, node.id)
            await add_script_to_folder(
                session,
                folder_id,
                script.id,
                template_trigger_id=template_trigger_id,
            )
            links_before_delete = await _folder_node_script_rows(session, folder_id)
            cloned_trigger_id = links_before_delete[0].trigger_id

            await delete_folder(session, folder_id, preserve_bindings=False)

            trigger_ids = await session.execute(select(Trigger.id).order_by(Trigger.id))
            schedule_ids = await session.execute(
                select(TriggerSchedule.trigger_id).order_by(TriggerSchedule.trigger_id)
            )

        self.assertNotEqual(cloned_trigger_id, template_trigger_id)
        self.assertEqual([row[0] for row in trigger_ids.all()], [])
        self.assertEqual([row[0] for row in schedule_ids.all()], [])


async def _folder_node_script_rows(session, folder_id: int) -> list[NodeScript]:
    result = await session.execute(
        select(NodeScript)
        .where(NodeScript.folder_id == folder_id)
        .order_by(NodeScript.node_id, NodeScript.script_id)
    )
    return list(result.scalars().all())


async def _manual_node_script_rows(session) -> list[NodeScript]:
    result = await session.execute(
        select(NodeScript)
        .where(NodeScript.folder_id.is_(None))
        .order_by(NodeScript.id)
    )
    return list(result.scalars().all())


async def _all_node_script_rows(session) -> list[NodeScript]:
    result = await session.execute(select(NodeScript).order_by(NodeScript.id))
    return list(result.scalars().all())
