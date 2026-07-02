import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node_hash_gc import NodeHashGc
from app.schemas.folder import NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate, ScriptUpdateContent
from app.services.folder_service import create_node_script
from app.services.gc_service import desired_hashes, enqueue_hash_gc_if_not_desired
from app.services.hash import calculate_script_hash
from app.services.node_service import create_node
from app.services.script_service import create_script, update_script_content


class NodeHashGcTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_desired_hashes_returns_current_hashes_for_node_scripts(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            other_node = await create_node(session, NodeCreate(name="node-2", host="203.0.113.11"))
            script_a = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            script_b = await create_script(session, ScriptCreate(name="script-b", content="echo b"))
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script_a.id),
            )
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script_b.id),
            )
            await create_node_script(
                session,
                NodeScriptCreate(node_id=other_node.id, script_id=script_b.id),
            )

            hashes = await desired_hashes(session, node.id)

        self.assertEqual(
            hashes,
            {
                calculate_script_hash("echo a"),
                calculate_script_hash("echo b"),
            },
        )

    async def test_gc_not_created_when_hash_is_still_desired(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id),
            )

            queued = await enqueue_hash_gc_if_not_desired(
                session,
                node.id,
                script.current_hash,
                reason="script_updated",
            )

            rows = await _gc_rows(session)

        self.assertIsNone(queued)
        self.assertEqual(rows, [])

    async def test_gc_created_when_hash_is_no_longer_desired(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            old_hash = script.current_hash
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id),
            )
            await update_script_content(
                session,
                script.id,
                ScriptUpdateContent(content="echo b"),
            )

            queued = await enqueue_hash_gc_if_not_desired(
                session,
                node.id,
                old_hash,
                reason="script_updated",
            )

        self.assertIsNotNone(queued)
        self.assertEqual(queued.node_id, node.id)
        self.assertEqual(queued.hash, old_hash)
        self.assertEqual(queued.reason, "script_updated")
        self.assertEqual(queued.status, "pending")
        self.assertEqual(queued.attempts, 0)
        self.assertIsNone(queued.last_attempt_at)

    async def test_duplicate_gc_is_not_created(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            old_hash = "old-hash"

            first = await enqueue_hash_gc_if_not_desired(
                session,
                node.id,
                old_hash,
                reason="script_deleted",
            )
            second = await enqueue_hash_gc_if_not_desired(
                session,
                node.id,
                old_hash,
                reason="script_deleted",
            )
            rows = await _gc_rows(session)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(rows), 1)


async def _gc_rows(session) -> list[NodeHashGc]:
    result = await session.execute(select(NodeHashGc).order_by(NodeHashGc.id))
    return list(result.scalars().all())
