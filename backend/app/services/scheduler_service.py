from __future__ import annotations

from uuid import UUID, uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_client import AgentClient
from app.models.node_script import NodeScript
from app.models.trigger import TriggerOnStartup, TriggerSchedule
from app.services.script_execution_service import DashboardScriptExecutionService


class TriggerExecutionScheduler:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        agent_client: AgentClient,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        self._session_maker = session_maker
        self._agent_client = agent_client
        self._scheduler = scheduler or AsyncIOScheduler()

    async def start(self) -> None:
        await self.sync_scheduled_jobs()
        if not self._scheduler.running:
            self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def sync_scheduled_jobs(self) -> None:
        async with self._session_maker() as session:
            result = await session.execute(
                select(NodeScript.id, TriggerSchedule.interval_seconds)
                .join(TriggerSchedule, TriggerSchedule.trigger_id == NodeScript.trigger_id)
                .order_by(NodeScript.id)
            )
            active_job_ids: set[str] = set()
            for node_script_id, interval_seconds in result.all():
                active_job_ids.add(_job_id(node_script_id))
                self.upsert_schedule_job(node_script_id, interval_seconds)

        for job in list(self._scheduler.get_jobs()):
            if job.id.startswith("node_script:") and job.id not in active_job_ids:
                self._scheduler.remove_job(job.id)

    async def run_on_startup_triggers(self) -> None:
        async with self._session_maker() as session:
            result = await session.execute(
                select(NodeScript.id)
                .join(TriggerOnStartup, TriggerOnStartup.trigger_id == NodeScript.trigger_id)
                .order_by(NodeScript.id)
            )
            node_script_ids = list(result.scalars().all())

        for node_script_id in node_script_ids:
            await self.run_schedule_fire(node_script_id)

    def upsert_schedule_job(self, node_script_id: int, interval_seconds: int) -> None:
        self._scheduler.add_job(
            self.run_schedule_fire,
            trigger=IntervalTrigger(seconds=interval_seconds),
            args=[node_script_id],
            id=_job_id(node_script_id),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=None,
        )

    def remove_schedule_job(self, node_script_id: int) -> None:
        job_id = _job_id(node_script_id)
        if self._scheduler.get_job(job_id) is not None:
            self._scheduler.remove_job(job_id)

    async def run_schedule_fire(
        self,
        node_script_id: int,
        request_id: UUID | None = None,
    ) -> None:
        fire_request_id = request_id or uuid4()
        async with self._session_maker() as session:
            service = DashboardScriptExecutionService(session, self._agent_client)
            try:
                await service.execute_node_script(
                    node_script_id,
                    request_id=fire_request_id,
                )
            except Exception:
                return

    def get_job(self, node_script_id: int):
        return self._scheduler.get_job(_job_id(node_script_id))


def _job_id(node_script_id: int) -> str:
    return f"node_script:{node_script_id}"
