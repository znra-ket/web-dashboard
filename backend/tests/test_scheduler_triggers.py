import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent_client.schemas import AgentScriptExecuteResponse
from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node import NodeLifecycleStatus
from app.models.node_script import NodeScript
from app.models.trigger import Trigger, TriggerSchedule
from app.schemas.folder import NodeScriptCreate
from app.schemas.node import NodeCreate
from app.schemas.script import ScriptCreate
from app.services.folder_service import create_node_script
from app.services.node_service import create_node
from app.services.scheduler_service import TriggerExecutionScheduler
from app.services.script_service import create_script
from app.services.trigger_service import (
    remove_trigger_from_node_script,
    create_schedule_trigger,
    set_on_startup_trigger_on_node_script,
    set_schedule_trigger_on_node_script,
    update_schedule_trigger,
)


class SchedulerTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_schedule_job_calls_execution_service(self) -> None:
        async with self.session_maker() as session:
            node_script, script_hash = await self._create_binding(session)

        agent = FakeSchedulerAgentClient()
        scheduler = TriggerExecutionScheduler(self.session_maker, agent)
        request_id = uuid4()

        await scheduler.run_schedule_fire(node_script.id, request_id=request_id)

        self.assertEqual(len(agent.execute_calls), 1)
        self.assertEqual(agent.execute_calls[0]["hash"], script_hash)
        self.assertEqual(agent.execute_calls[0]["request_id"], request_id)

    async def test_schedule_fire_generates_new_request_id_per_fire(self) -> None:
        async with self.session_maker() as session:
            node_script, _ = await self._create_binding(session)

        agent = FakeSchedulerAgentClient()
        scheduler = TriggerExecutionScheduler(self.session_maker, agent)

        await scheduler.run_schedule_fire(node_script.id)
        await scheduler.run_schedule_fire(node_script.id)

        self.assertEqual(len(agent.execute_calls), 2)
        self.assertNotEqual(agent.execute_calls[0]["request_id"], agent.execute_calls[1]["request_id"])

    async def test_same_schedule_fire_can_reuse_request_id_for_retry(self) -> None:
        async with self.session_maker() as session:
            node_script, _ = await self._create_binding(session)

        agent = FakeSchedulerAgentClient()
        scheduler = TriggerExecutionScheduler(self.session_maker, agent)
        request_id = uuid4()

        await scheduler.run_schedule_fire(node_script.id, request_id=request_id)
        await scheduler.run_schedule_fire(node_script.id, request_id=request_id)

        self.assertEqual([call["request_id"] for call in agent.execute_calls], [request_id, request_id])

    async def test_on_startup_runner_executes_startup_triggers(self) -> None:
        async with self.session_maker() as session:
            node_script, script_hash = await self._create_binding(session)
            await set_on_startup_trigger_on_node_script(session, node_script.id)

        agent = FakeSchedulerAgentClient()
        scheduler = TriggerExecutionScheduler(self.session_maker, agent)

        await scheduler.run_on_startup_triggers()

        self.assertEqual(len(agent.execute_calls), 1)
        self.assertEqual(agent.execute_calls[0]["hash"], script_hash)

    async def test_set_and_update_schedule_trigger_updates_scheduler_job(self) -> None:
        async with self.session_maker() as session:
            node_script, _ = await self._create_binding(session)
            scheduler = FakeJobRegistry()

            scheduled = await set_schedule_trigger_on_node_script(
                session,
                node_script.id,
                interval_seconds=60,
                scheduler=scheduler,
            )
            schedule = await session.get(TriggerSchedule, scheduled.trigger_id)
            updated = await update_schedule_trigger(
                session,
                node_script.id,
                interval_seconds=120,
                scheduler=scheduler,
            )
            updated_schedule = await session.get(TriggerSchedule, updated.trigger_id)

        self.assertEqual(schedule.interval_seconds, 120)
        self.assertEqual(updated_schedule.interval_seconds, 120)
        self.assertEqual(scheduler.upsert_calls, [(node_script.id, 60), (node_script.id, 120)])

    async def test_remove_trigger_updates_row_when_no_manual_duplicate_exists(self) -> None:
        async with self.session_maker() as session:
            node_script, _ = await self._create_binding(session)
            scheduler = FakeJobRegistry()
            scheduled = await set_schedule_trigger_on_node_script(
                session,
                node_script.id,
                interval_seconds=60,
                scheduler=scheduler,
            )
            old_trigger_id = scheduled.trigger_id

            await remove_trigger_from_node_script(session, node_script.id, scheduler=scheduler)
            loaded = await session.get(NodeScript, node_script.id)
            old_trigger = await session.scalar(select(Trigger.id).where(Trigger.id == old_trigger_id))

        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.trigger_id)
        self.assertIsNone(old_trigger)
        self.assertEqual(scheduler.remove_calls, [node_script.id])

    async def test_remove_trigger_deletes_triggered_row_when_manual_presence_exists(self) -> None:
        async with self.session_maker() as session:
            node, script = await self._create_node_and_script(session)
            manual = await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id),
            )
            trigger = await create_schedule_trigger(session, interval_seconds=60)
            triggered = await create_node_script(
                session,
                NodeScriptCreate(node_id=node.id, script_id=script.id, trigger_id=trigger.id),
            )
            old_trigger_id = triggered.trigger_id

            await remove_trigger_from_node_script(session, triggered.id)
            manual_loaded = await session.get(NodeScript, manual.id)
            triggered_loaded = await session.get(NodeScript, triggered.id)
            old_trigger = await session.scalar(select(Trigger.id).where(Trigger.id == old_trigger_id))

        self.assertIsNotNone(manual_loaded)
        self.assertIsNone(triggered_loaded)
        self.assertIsNone(old_trigger)

    async def test_manual_link_does_not_create_trigger_row(self) -> None:
        async with self.session_maker() as session:
            await self._create_binding(session)
            trigger_ids = await session.execute(select(Trigger.id))

        self.assertEqual(trigger_ids.all(), [])

    async def test_sync_scheduled_jobs_adds_interval_job(self) -> None:
        async with self.session_maker() as session:
            node_script, _ = await self._create_binding(session)
            await set_schedule_trigger_on_node_script(session, node_script.id, interval_seconds=45)

        agent = FakeSchedulerAgentClient()
        scheduler = TriggerExecutionScheduler(self.session_maker, agent)
        await scheduler.sync_scheduled_jobs()
        job = scheduler.get_job(node_script.id)

        self.assertIsNotNone(job)
        self.assertEqual(job.trigger.interval.seconds, 45)

    async def _create_binding(self, session) -> tuple[NodeScript, str]:
        node, script = await self._create_node_and_script(session)
        node_script = await create_node_script(
            session,
            NodeScriptCreate(node_id=node.id, script_id=script.id),
        )
        return node_script, script.current_hash

    async def _create_node_and_script(self, session):
        node = await create_node(
            session,
            NodeCreate(
                name=f"node-{uuid4()}",
                host="127.0.0.1",
                agent_port=8766,
                lifecycle_status=NodeLifecycleStatus.ACTIVE,
            ),
        )
        script = await create_script(
            session,
            ScriptCreate(name=f"script-{uuid4()}", content="#!/usr/bin/env bash\necho ok\n"),
        )
        return node, script


class FakeSchedulerAgentClient:
    def __init__(self) -> None:
        self.execute_calls = []

    async def execute_script(
        self,
        node,
        script_hash: str,
        request_id: UUID,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> AgentScriptExecuteResponse:
        self.execute_calls.append(
            {
                "node_id": node.id,
                "hash": script_hash,
                "request_id": request_id,
                "args": args or [],
                "env": env or {},
                "timeout_seconds": timeout_seconds,
            }
        )
        return AgentScriptExecuteResponse(
            exit_code=0,
            stdout="ok\n",
            stderr="",
            duration_ms=1,
            timed_out=False,
        )


class FakeJobRegistry:
    def __init__(self) -> None:
        self.upsert_calls = []
        self.remove_calls = []

    def upsert_schedule_job(self, node_script_id: int, interval_seconds: int) -> None:
        self.upsert_calls.append((node_script_id, interval_seconds))

    def remove_schedule_job(self, node_script_id: int) -> None:
        self.remove_calls.append(node_script_id)
