import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent_client.schemas import AgentScriptUploadResponse
from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node import NodeLifecycleStatus
from app.models.node_script import NodeScript
from app.models.script import Script
from app.models.trigger import Trigger, TriggerSchedule
from app.schemas.node import NodeCreate
from app.services.exceptions import AgentNetworkError
from app.services.hash import calculate_script_hash
from app.services.metrics_onboarding_service import (
    METRICS_SCRIPTS,
    METRICS_TRIGGER_INTERVAL_SECONDS,
    Stage3MetricsOnboardingService,
    seed_metrics_scripts,
)
from app.services.node_service import create_node


class Stage3MetricsOnboardingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_metrics_scripts_seed_creates_normal_script_rows(self) -> None:
        async with self.session_maker() as session:
            scripts = await seed_metrics_scripts(session)
            rows = await _scripts(session)

        self.assertEqual([script.name for script in scripts], ["xray_status", "detect_stack", "speedtest"])
        self.assertEqual([row.name for row in rows], ["xray_status", "detect_stack", "speedtest"])
        self.assertEqual(
            {row.name: row.current_hash for row in rows},
            {definition.name: calculate_script_hash(definition.content) for definition in METRICS_SCRIPTS},
        )
        self.assertFalse(any(hasattr(row, "agent_status") for row in rows))

    async def test_stage3_uploads_metrics_and_creates_independent_scheduled_links(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.METRICS_UPLOADING,
                ),
            )
            agent = FakeMetricsAgentClient()

            updated = await Stage3MetricsOnboardingService(session, agent).upload_metrics_and_create_links(node.id)
            links = await _node_scripts(session)
            schedules = await _trigger_schedules(session)
            trigger_rows = await _triggers(session)

        self.assertEqual(updated.lifecycle_status, NodeLifecycleStatus.ACTIVE.value)
        self.assertEqual(
            agent.upload_calls,
            [(node.id, definition.content) for definition in METRICS_SCRIPTS],
        )
        self.assertEqual(len(links), 3)
        self.assertTrue(all(link.node_id == node.id and link.folder_id is None for link in links))
        trigger_ids = [link.trigger_id for link in links]
        self.assertEqual(len(set(trigger_ids)), 3)
        self.assertEqual({trigger.type for trigger in trigger_rows}, {"schedule"})
        self.assertEqual(
            {schedule.trigger_id: schedule.interval_seconds for schedule in schedules},
            {trigger_id: METRICS_TRIGGER_INTERVAL_SECONDS for trigger_id in trigger_ids},
        )

    async def test_stage3_failure_sets_failed_metrics_upload(self) -> None:
        async with self.session_maker() as session:
            node = await create_node(
                session,
                NodeCreate(
                    name="node-1",
                    host="203.0.113.10",
                    lifecycle_status=NodeLifecycleStatus.METRICS_UPLOADING,
                ),
            )
            agent = FakeMetricsAgentClient(fail_on_call=2)

            with self.assertRaises(AgentNetworkError):
                await Stage3MetricsOnboardingService(session, agent).upload_metrics_and_create_links(node.id)

            loaded = await session.get(type(node), node.id)
            links = await _node_scripts(session)

        self.assertEqual(loaded.lifecycle_status, NodeLifecycleStatus.FAILED_METRICS_UPLOAD.value)
        self.assertEqual(links, [])


class FakeMetricsAgentClient:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.upload_calls = []

    async def upload_script(self, node, script_source: str) -> AgentScriptUploadResponse:
        self.upload_calls.append((node.id, script_source))
        if self.fail_on_call == len(self.upload_calls):
            raise AgentNetworkError("network")
        return AgentScriptUploadResponse(hash=calculate_script_hash(script_source))


async def _scripts(session) -> list[Script]:
    result = await session.execute(select(Script).order_by(Script.id))
    return list(result.scalars().all())


async def _node_scripts(session) -> list[NodeScript]:
    result = await session.execute(select(NodeScript).order_by(NodeScript.id))
    return list(result.scalars().all())


async def _triggers(session) -> list[Trigger]:
    result = await session.execute(select(Trigger).order_by(Trigger.id))
    return list(result.scalars().all())


async def _trigger_schedules(session) -> list[TriggerSchedule]:
    result = await session.execute(select(TriggerSchedule).order_by(TriggerSchedule.trigger_id))
    return list(result.scalars().all())
