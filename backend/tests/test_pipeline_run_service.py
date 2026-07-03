import json
import tempfile
import unittest
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent_client.schemas import AgentScriptExecuteResponse
from app.db.migration_runner import run_migrations
from app.db.session import create_database_engine
from app.models.node import NodeLifecycleStatus
from app.models.pipeline import PipelineRunStatus, PipelineRunStep, PipelineRunStepStatus, PipelineStepArgSourceType
from app.schemas.node import NodeCreate
from app.schemas.pipeline import PipelineCreate, PipelineStepArgCreate, PipelineStepCreate, PipelineStepUpdate
from app.schemas.script import ScriptCreate
from app.services.exceptions import AgentTimeoutError
from app.services.node_service import create_node
from app.services.pipeline_run_service import PipelineRunService
from app.services.pipeline_service import (
    create_pipeline,
    create_pipeline_step,
    create_pipeline_step_arg,
    update_pipeline_step,
)
from app.services.script_service import create_script


class PipelineRunServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_database_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        await run_migrations(self.engine)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self._suffix = 0

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_successful_pipeline_run_resolves_literal_and_step_output_args(self) -> None:
        async with self.session_maker() as session:
            pipeline = await create_pipeline(session, PipelineCreate(name="deploy"))
            first_step = await self._create_step(session, pipeline.id, 1, "collect")
            second_step = await self._create_step(session, pipeline.id, 2, "apply")
            await create_pipeline_step_arg(
                session,
                second_step.id,
                PipelineStepArgCreate(
                    arg_index=0,
                    source_type=PipelineStepArgSourceType.LITERAL,
                    literal_value="--ip",
                ),
            )
            await create_pipeline_step_arg(
                session,
                second_step.id,
                PipelineStepArgCreate(
                    arg_index=1,
                    source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                    source_step_id=first_step.id,
                    json_field="ip",
                ),
            )
            executor = FakeScriptExecutionService(
                [
                    _execute_response(0, stdout='{"ip":"203.0.113.5"}'),
                    _execute_response(0, stdout="ok"),
                ]
            )
            service = PipelineRunService(session, executor)

            run = await service.run_pipeline(pipeline.id, env={"MODE": "test"}, timeout_seconds=9)
            run_steps = await _run_steps(session, run.id)

        self.assertEqual(run.status, PipelineRunStatus.SUCCEEDED.value)
        self.assertIsNone(run.error)
        self.assertEqual([step.status for step in run_steps], [PipelineRunStepStatus.SUCCEEDED.value] * 2)
        self.assertEqual(json.loads(run_steps[0].resolved_args), [])
        self.assertEqual(json.loads(run_steps[1].resolved_args), ["--ip", "203.0.113.5"])
        self.assertEqual(
            [(call["args"], call["env"], call["timeout_seconds"]) for call in executor.calls],
            [([], {"MODE": "test"}, 9), (["--ip", "203.0.113.5"], {"MODE": "test"}, 9)],
        )
        self.assertEqual(
            run_steps[0].request_id,
            str(uuid5(NAMESPACE_URL, f"pipeline-run:{run.id}:step:{first_step.id}")),
        )
        self.assertIsInstance(executor.calls[0]["request_id"], UUID)

    async def test_step_output_requires_json_object_and_stops_pipeline(self) -> None:
        async with self.session_maker() as session:
            pipeline = await create_pipeline(session, PipelineCreate(name="bad-json"))
            first_step = await self._create_step(session, pipeline.id, 1, "collect")
            second_step = await self._create_step(session, pipeline.id, 2, "apply")
            third_step = await self._create_step(session, pipeline.id, 3, "cleanup")
            await create_pipeline_step_arg(
                session,
                second_step.id,
                PipelineStepArgCreate(
                    arg_index=0,
                    source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                    source_step_id=first_step.id,
                    json_field="ip",
                ),
            )
            executor = FakeScriptExecutionService([_execute_response(0, stdout="not-json")])
            service = PipelineRunService(session, executor)

            run = await service.run_pipeline(pipeline.id)
            run_steps = await _run_steps(session, run.id)

        self.assertEqual(run.status, PipelineRunStatus.FAILED.value)
        self.assertEqual([step.step_id for step in run_steps], [first_step.id, second_step.id, third_step.id])
        self.assertEqual(
            [step.status for step in run_steps],
            [
                PipelineRunStepStatus.SUCCEEDED.value,
                PipelineRunStepStatus.FAILED.value,
                PipelineRunStepStatus.SKIPPED.value,
            ],
        )
        self.assertIn("not valid JSON", run_steps[1].error)
        self.assertEqual(len(executor.calls), 1)

    async def test_failed_step_stops_pipeline_without_rollback(self) -> None:
        async with self.session_maker() as session:
            pipeline = await create_pipeline(session, PipelineCreate(name="failure"))
            first_step = await self._create_step(session, pipeline.id, 1, "first")
            second_step = await self._create_step(session, pipeline.id, 2, "second")
            executor = FakeScriptExecutionService([_execute_response(23, stderr="boom")])
            service = PipelineRunService(session, executor)

            run = await service.run_pipeline(pipeline.id)
            run_steps = await _run_steps(session, run.id)

        self.assertEqual(run.status, PipelineRunStatus.FAILED.value)
        self.assertEqual(run.error, "exit_code=23")
        self.assertEqual(run_steps[0].step_id, first_step.id)
        self.assertEqual(run_steps[0].status, PipelineRunStepStatus.FAILED.value)
        self.assertEqual(run_steps[0].exit_code, 23)
        self.assertEqual(run_steps[0].stderr, "boom")
        self.assertEqual(run_steps[1].step_id, second_step.id)
        self.assertEqual(run_steps[1].status, PipelineRunStepStatus.SKIPPED.value)
        self.assertEqual(len(executor.calls), 1)

    async def test_transport_error_fails_current_step_and_skips_tail(self) -> None:
        async with self.session_maker() as session:
            pipeline = await create_pipeline(session, PipelineCreate(name="transport"))
            first_step = await self._create_step(session, pipeline.id, 1, "first")
            second_step = await self._create_step(session, pipeline.id, 2, "second")
            executor = FakeScriptExecutionService([AgentTimeoutError("agent timeout")])
            service = PipelineRunService(session, executor)

            run = await service.run_pipeline(pipeline.id)
            run_steps = await _run_steps(session, run.id)

        self.assertEqual(run.status, PipelineRunStatus.FAILED.value)
        self.assertEqual(run_steps[0].step_id, first_step.id)
        self.assertEqual(run_steps[0].status, PipelineRunStepStatus.FAILED.value)
        self.assertEqual(run_steps[0].error, "agent timeout")
        self.assertEqual(run_steps[1].step_id, second_step.id)
        self.assertEqual(run_steps[1].status, PipelineRunStepStatus.SKIPPED.value)

    async def test_missing_json_field_fails_current_step(self) -> None:
        async with self.session_maker() as session:
            pipeline = await create_pipeline(session, PipelineCreate(name="missing-field"))
            first_step = await self._create_step(session, pipeline.id, 1, "collect")
            second_step = await self._create_step(session, pipeline.id, 2, "apply")
            await create_pipeline_step_arg(
                session,
                second_step.id,
                PipelineStepArgCreate(
                    arg_index=0,
                    source_type=PipelineStepArgSourceType.STEP_OUTPUT,
                    source_step_id=first_step.id,
                    json_field="ip",
                ),
            )
            executor = FakeScriptExecutionService([_execute_response(0, stdout='{"host":"example"}')])
            service = PipelineRunService(session, executor)

            run = await service.run_pipeline(pipeline.id)
            run_steps = await _run_steps(session, run.id)

        self.assertEqual(run.status, PipelineRunStatus.FAILED.value)
        self.assertEqual(run_steps[1].status, PipelineRunStepStatus.FAILED.value)
        self.assertIn("json_field not found", run_steps[1].error)

    async def test_history_keeps_snapshot_after_pipeline_definition_changes(self) -> None:
        async with self.session_maker() as session:
            pipeline = await create_pipeline(session, PipelineCreate(name="snapshot"))
            step = await self._create_step(session, pipeline.id, 1, "original")
            await create_pipeline_step_arg(
                session,
                step.id,
                PipelineStepArgCreate(
                    arg_index=0,
                    source_type=PipelineStepArgSourceType.LITERAL,
                    literal_value="before-change",
                ),
            )
            original_node_id = step.node_id
            original_script_id = step.script_id
            executor = FakeScriptExecutionService([_execute_response(0, stdout="done")])
            service = PipelineRunService(session, executor)

            run = await service.run_pipeline(pipeline.id)
            original_run_step = (await _run_steps(session, run.id))[0]
            new_node_id, new_script_id = await self._create_node_and_script(session, "replacement")
            await update_pipeline_step(
                session,
                step.id,
                PipelineStepUpdate(position=1, node_id=new_node_id, script_id=new_script_id),
            )
            loaded_run_step = (await _run_steps(session, run.id))[0]

        self.assertEqual(loaded_run_step.id, original_run_step.id)
        self.assertEqual(loaded_run_step.node_id, original_node_id)
        self.assertEqual(loaded_run_step.script_id, original_script_id)
        self.assertEqual(json.loads(loaded_run_step.resolved_args), ["before-change"])
        self.assertNotEqual(loaded_run_step.node_id, new_node_id)
        self.assertNotEqual(loaded_run_step.script_id, new_script_id)

    async def _create_step(self, session, pipeline_id: int, position: int, suffix: str):
        node_id, script_id = await self._create_node_and_script(session, suffix)
        return await create_pipeline_step(
            session,
            pipeline_id,
            PipelineStepCreate(position=position, node_id=node_id, script_id=script_id),
        )

    async def _create_node_and_script(self, session, suffix: str) -> tuple[int, int]:
        self._suffix += 1
        node = await create_node(
            session,
            NodeCreate(
                name=f"node-{suffix}-{self._suffix}",
                host=f"198.51.100.{self._suffix}",
                lifecycle_status=NodeLifecycleStatus.ACTIVE,
            ),
        )
        script = await create_script(
            session,
            ScriptCreate(name=f"script-{suffix}-{self._suffix}", content=f"echo {suffix}"),
        )
        return node.id, script.id


class FakeScriptExecutionService:
    def __init__(self, responses: list[AgentScriptExecuteResponse | Exception]) -> None:
        self._responses = responses
        self.calls = []

    async def execute_node_script(
        self,
        node_script_id: int,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        request_id: UUID | None = None,
    ) -> AgentScriptExecuteResponse:
        self.calls.append(
            {
                "node_script_id": node_script_id,
                "args": args or [],
                "env": env or {},
                "timeout_seconds": timeout_seconds,
                "request_id": request_id,
            }
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _execute_response(
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
    duration_ms: int = 1,
    timed_out: bool = False,
    error_class: str | None = None,
) -> AgentScriptExecuteResponse:
    return AgentScriptExecuteResponse(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timed_out=timed_out,
        error_class=error_class,
        stderr_truncated=False,
    )


async def _run_steps(session, run_id: int) -> list[PipelineRunStep]:
    result = await session.execute(
        select(PipelineRunStep).where(PipelineRunStep.pipeline_run_id == run_id).order_by(PipelineRunStep.id)
    )
    return list(result.scalars().all())
