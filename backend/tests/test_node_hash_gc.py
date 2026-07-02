import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node_hash_gc import NodeHashGc
from app.models.node_hash_gc import NodeHashGcStatus
from app.schemas.folder import NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate, ScriptUpdateContent
from app.services.exceptions import AgentNetworkError, AgentScriptHashMissingError
from app.services.folder_service import create_node_script
from app.services.gc_service import HashGcService, desired_hashes, enqueue_hash_gc_if_not_desired
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
            node_id = node.id
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            old_hash = script.current_hash
            await create_node_script(
                session,
                NodeScriptCreate(node_id=node_id, script_id=script.id),
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
        self.assertEqual(queued.node_id, node_id)
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

    async def test_script_update_creates_gc_for_affected_node(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            old_hash = script.current_hash
            await create_node_script(session, NodeScriptCreate(node_id=node.id, script_id=script.id))

            await update_script_content(session, script.id, ScriptUpdateContent(content="echo b"))
            rows = await _gc_rows(session)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].node_id, node.id)
        self.assertEqual(rows[0].hash, old_hash)
        self.assertEqual(rows[0].reason, "script_updated")
        self.assertEqual(rows[0].status, NodeHashGcStatus.PENDING.value)

    async def test_script_update_proactively_uploads_to_online_node(self) -> None:
        async with self.session_maker() as session:
            active_node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status="active",
                ),
            )
            active_node_id = active_node.id
            offline_node = await create_node(session, NodeCreate(name="node-2", host="203.0.113.11"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            await create_node_script(session, NodeScriptCreate(node_id=active_node_id, script_id=script.id))
            await create_node_script(session, NodeScriptCreate(node_id=offline_node.id, script_id=script.id))
            agent = FakeGcAgentClient()

            await update_script_content(
                session,
                script.id,
                ScriptUpdateContent(content="echo b"),
                agent_client=agent,
            )

        self.assertEqual(agent.upload_calls, [(active_node_id, "echo b")])

    async def test_proactive_upload_failure_does_not_rollback_script_update_or_gc(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status="active",
                ),
            )
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            old_hash = script.current_hash
            await create_node_script(session, NodeScriptCreate(node_id=node.id, script_id=script.id))
            agent = FakeGcAgentClient(upload_errors=[AgentNetworkError("network")])

            updated = await update_script_content(
                session,
                script.id,
                ScriptUpdateContent(content="echo b"),
                agent_client=agent,
            )
            rows = await _gc_rows(session)

        self.assertEqual(updated.content, "echo b")
        self.assertEqual(updated.current_hash, calculate_script_hash("echo b"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].hash, old_hash)
        self.assertEqual(rows[0].status, NodeHashGcStatus.PENDING.value)

    async def test_hash_gc_cancelled_if_hash_is_desired_again(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            script = await create_script(session, ScriptCreate(name="script-a", content="echo a"))
            await create_node_script(session, NodeScriptCreate(node_id=node.id, script_id=script.id))
            item = NodeHashGc(
                node_id=node.id,
                hash=script.current_hash,
                reason="script_updated",
                status=NodeHashGcStatus.PENDING.value,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)

            processed = await HashGcService(session, FakeGcAgentClient()).process_item(item)

        self.assertEqual(processed.status, NodeHashGcStatus.CANCELLED.value)

    async def test_hash_gc_done_when_delete_succeeds(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            item = NodeHashGc(
                node_id=node.id,
                hash="old-hash",
                reason="script_updated",
                status=NodeHashGcStatus.PENDING.value,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            agent = FakeGcAgentClient()

            processed = await HashGcService(session, agent).process_item(item)

        self.assertEqual(processed.status, NodeHashGcStatus.DONE.value)
        self.assertEqual(agent.delete_calls, [(node.id, "old-hash")])
        self.assertEqual(processed.attempts, 0)
        self.assertIsNotNone(processed.last_attempt_at)

    async def test_hash_gc_done_when_remote_hash_is_already_missing(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            item = NodeHashGc(
                node_id=node.id,
                hash="old-hash",
                reason="script_updated",
                status=NodeHashGcStatus.PENDING.value,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            agent = FakeGcAgentClient(delete_errors=[AgentScriptHashMissingError("missing")])

            processed = await HashGcService(session, agent).process_item(item)

        self.assertEqual(processed.status, NodeHashGcStatus.DONE.value)

    async def test_hash_gc_failed_after_attempt_limit(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(session, NodeCreate(name="node-1", host="203.0.113.10"))
            item = NodeHashGc(
                node_id=node.id,
                hash="old-hash",
                reason="script_updated",
                status=NodeHashGcStatus.PENDING.value,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            agent = FakeGcAgentClient(
                delete_errors=[
                    AgentNetworkError("network"),
                    AgentNetworkError("network"),
                ]
            )
            service = HashGcService(session, agent, max_attempts=2)

            first = await service.process_item(item)
            second = await service.process_item(first)

        self.assertEqual(first.attempts, 2)
        self.assertEqual(second.status, NodeHashGcStatus.FAILED.value)
        self.assertEqual(second.attempts, 2)


async def _gc_rows(session) -> list[NodeHashGc]:
    result = await session.execute(select(NodeHashGc).order_by(NodeHashGc.id))
    return list(result.scalars().all())


class FakeGcAgentClient:
    def __init__(
        self,
        delete_errors: list[Exception] | None = None,
        upload_errors: list[Exception] | None = None,
    ) -> None:
        self.delete_errors = delete_errors or []
        self.upload_errors = upload_errors or []
        self.upload_calls = []
        self.delete_calls = []

    async def upload_script(self, node, script_source: str):
        self.upload_calls.append((node.id, script_source))
        if self.upload_errors:
            raise self.upload_errors.pop(0)

    async def delete_script_hash(self, node, script_hash: str) -> None:
        self.delete_calls.append((node.id, script_hash))
        if self.delete_errors:
            raise self.delete_errors.pop(0)
