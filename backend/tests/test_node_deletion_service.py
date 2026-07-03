import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.folder import FolderNode
from app.models.node import Node, NodeLifecycleStatus
from app.models.node_hash_gc import NodeHashGc, NodeHashGcStatus
from app.models.node_script import NodeScript
from app.models.pipeline import PipelineRun, PipelineRunStatus, PipelineRunStep, PipelineRunStepStatus, PipelineStep
from app.models.trigger import Trigger
from app.schemas.folder import FolderCreate, NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.pipeline import PipelineCreate, PipelineStepCreate
from app.schemas.script import ScriptCreate
from app.services.exceptions import AgentTimeoutError, ValidationError
from app.services.folder_service import add_node_to_folder, create_folder, create_node_script
from app.services.mtls_onboarding_service import MtlsProbeResult, MtlsProbeService
from app.services.node_deletion_service import OFFLINE_DELETE_WARNING, NodeDeletionService
from app.services.node_service import create_node
from app.services.pipeline_service import create_pipeline, create_pipeline_step
from app.services.script_service import create_script
from app.services.trigger_service import create_schedule_trigger


class NodeDeletionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_online_delete_unpairs_before_local_delete(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_active_node(session)
            node_id = node.id
            agent = FakeDeleteAgentClient()
            service = NodeDeletionService(session, agent)

            result = await service.delete_online(node_id)
            removed = await session.get(Node, node_id)

        self.assertTrue(result.deleted)
        self.assertEqual(agent.calls, [("unpair", node_id, NodeLifecycleStatus.UNPAIRING.value)])
        self.assertIsNone(removed)

    async def test_offline_delete_deletes_locally_with_warning_without_agent_call(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_active_node(session)
            node_id = node.id
            agent = FakeDeleteAgentClient()
            service = NodeDeletionService(session, agent)

            result = await service.delete_offline(node_id)
            removed = await session.get(Node, node_id)

        self.assertTrue(result.deleted)
        self.assertEqual(result.warnings, (OFFLINE_DELETE_WARNING,))
        self.assertEqual(agent.calls, [])
        self.assertIsNone(removed)

    async def test_full_uninstall_calls_uninstall_before_local_delete(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_active_node(session)
            node_id = node.id
            agent = FakeDeleteAgentClient()
            service = NodeDeletionService(session, agent)

            result = await service.uninstall_online(node_id)
            removed = await session.get(Node, node_id)

        self.assertTrue(result.deleted)
        self.assertEqual(agent.calls, [("uninstall", node_id, NodeLifecycleStatus.UNINSTALLING.value)])
        self.assertIsNone(removed)

    async def test_full_uninstall_is_not_available_offline(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_active_node(session)
            agent = FakeDeleteAgentClient()
            service = NodeDeletionService(session, agent)

            with self.assertRaises(ValidationError):
                await service.uninstall_offline(node.id)

            still_exists = await session.get(Node, node.id)

        self.assertIsNotNone(still_exists)
        self.assertEqual(agent.calls, [])

    async def test_failed_unpair_keeps_node_in_database(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_active_node(session)
            node_id = node.id
            agent = FakeDeleteAgentClient(unpair_error=AgentTimeoutError("timeout"))
            service = NodeDeletionService(session, agent)

            with self.assertRaises(AgentTimeoutError):
                await service.delete_online(node_id)

            kept = await session.get(Node, node_id)

        self.assertIsNotNone(kept)
        self.assertEqual(kept.lifecycle_status, NodeLifecycleStatus.UNPAIRING.value)

    async def test_failed_uninstall_keeps_node_in_database(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_active_node(session)
            node_id = node.id
            agent = FakeDeleteAgentClient(uninstall_error=AgentTimeoutError("timeout"))
            service = NodeDeletionService(session, agent)

            with self.assertRaises(AgentTimeoutError):
                await service.uninstall_online(node_id)

            kept = await session.get(Node, node_id)

        self.assertIsNotNone(kept)
        self.assertEqual(kept.lifecycle_status, NodeLifecycleStatus.UNINSTALLING.value)

    async def test_local_delete_cascades_operational_state_but_keeps_run_history(self) -> None:
        async with self.session_maker() as session:
            fixture = await self._create_local_delete_fixture(session)
            service = NodeDeletionService(session, FakeDeleteAgentClient())

            await service.delete_offline(fixture.node_id)

            folder_nodes = await _ids(session, select(FolderNode.node_id))
            node_scripts = await _ids(session, select(NodeScript.node_id))
            pipeline_steps = await _ids(session, select(PipelineStep.id))
            triggers = await _ids(session, select(Trigger.id))
            gc_rows = await _ids(session, select(NodeHashGc.id))
            history = await session.get(PipelineRunStep, fixture.run_step_id)

        self.assertEqual(folder_nodes, [])
        self.assertEqual(node_scripts, [])
        self.assertEqual(pipeline_steps, [])
        self.assertEqual(triggers, [])
        self.assertEqual(gc_rows, [])
        self.assertIsNotNone(history)
        self.assertEqual(history.node_id, fixture.node_id)
        self.assertEqual(history.script_id, fixture.script_id)
        self.assertEqual(history.step_id, fixture.step_id)
        self.assertEqual(history.stdout, "historic")

    async def test_certificate_binding_is_not_trusted_after_node_delete(self) -> None:
        async with self.session_maker() as session:
            node = await self._create_active_node(session, fingerprint="sha256:deleted")
            service = MtlsProbeService(session, FakeProbeTransport(MtlsProbeResult(True, "sha256:deleted")))

            trusted_before = await service.is_active_fingerprint_trusted("sha256:deleted")
            await NodeDeletionService(session, FakeDeleteAgentClient()).delete_offline(node.id)
            trusted_after = await service.is_active_fingerprint_trusted("sha256:deleted")

        self.assertTrue(trusted_before)
        self.assertFalse(trusted_after)

    async def _create_active_node(
        self,
        session,
        fingerprint: str | None = "sha256:node",
    ) -> Node:
        return await create_node(
            session,
            NodeCreate(
                name="node-1",
                host="203.0.113.10",
                lifecycle_status=NodeLifecycleStatus.ACTIVE,
                agent_cert_fingerprint=fingerprint,
            ),
        )

    async def _create_local_delete_fixture(self, session):
        node = await self._create_active_node(session)
        script = await create_script(session, ScriptCreate(name="script-1", content="echo ok"))
        folder = await create_folder(session, FolderCreate(name="ops"))
        await add_node_to_folder(session, folder.id, node.id)

        trigger = await create_schedule_trigger(session, interval_seconds=60)
        await create_node_script(
            session,
            NodeScriptCreate(node_id=node.id, script_id=script.id, trigger_id=trigger.id),
        )
        session.add(
            NodeHashGc(
                node_id=node.id,
                hash="a" * 64,
                reason="test",
                status=NodeHashGcStatus.PENDING.value,
                attempts=0,
            )
        )
        await session.commit()

        pipeline = await create_pipeline(session, PipelineCreate(name="pipeline"))
        step = await create_pipeline_step(
            session,
            pipeline.id,
            PipelineStepCreate(position=1, node_id=node.id, script_id=script.id),
        )
        run = PipelineRun(
            pipeline_id=pipeline.id,
            status=PipelineRunStatus.SUCCEEDED.value,
            started_at="2026-07-03 10:00:00",
            finished_at="2026-07-03 10:00:01",
            error=None,
        )
        session.add(run)
        await session.flush()
        run_step = PipelineRunStep(
            pipeline_run_id=run.id,
            step_id=step.id,
            node_id=node.id,
            script_id=script.id,
            resolved_args="[]",
            request_id="00000000-0000-0000-0000-000000000001",
            status=PipelineRunStepStatus.SUCCEEDED.value,
            started_at="2026-07-03 10:00:00",
            finished_at="2026-07-03 10:00:01",
            exit_code=0,
            stdout="historic",
            stderr="",
            timed_out=False,
            error=None,
            duration_ms=1,
        )
        session.add(run_step)
        await session.commit()
        return type(
            "LocalDeleteFixture",
            (),
            {
                "node_id": node.id,
                "script_id": script.id,
                "step_id": step.id,
                "run_step_id": run_step.id,
            },
        )()


class FakeDeleteAgentClient:
    def __init__(
        self,
        unpair_error: Exception | None = None,
        uninstall_error: Exception | None = None,
    ) -> None:
        self._unpair_error = unpair_error
        self._uninstall_error = uninstall_error
        self.calls = []

    async def unpair(self, node: Node):
        self.calls.append(("unpair", node.id, node.lifecycle_status))
        if self._unpair_error is not None:
            raise self._unpair_error
        return type("UnpairResponse", (), {"agent_state": "unpaired", "removed_paths": []})()

    async def uninstall(self, node: Node):
        self.calls.append(("uninstall", node.id, node.lifecycle_status))
        if self._uninstall_error is not None:
            raise self._uninstall_error
        return type(
            "UninstallResponse",
            (),
            {"agent_state": "unpaired", "dry_run": True, "planned_paths": [], "removed_paths": []},
        )()


class FakeProbeTransport:
    def __init__(self, result: MtlsProbeResult) -> None:
        self._result = result

    async def probe(self, node: Node) -> MtlsProbeResult:
        return self._result


async def _ids(session, statement) -> list[int]:
    result = await session.execute(statement)
    return list(result.scalars().all())
