from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_client.schemas import AgentScriptExecuteResponse
from app.models.node_script import NodeScript
from app.models.pipeline import (
    Pipeline,
    PipelineRun,
    PipelineRunStatus,
    PipelineRunStep,
    PipelineRunStepStatus,
    PipelineStep,
    PipelineStepArg,
    PipelineStepArgSourceType,
)
from app.services.exceptions import AgentClientError, DomainError, NotFoundError
from app.services.script_execution_service import DashboardScriptExecutionService


class PipelineRunService:
    def __init__(
        self,
        session: AsyncSession,
        script_execution_service: DashboardScriptExecutionService,
    ) -> None:
        self._session = session
        self._script_execution_service = script_execution_service

    async def run_pipeline(
        self,
        pipeline_id: int,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> PipelineRun:
        definition = await self._load_definition(pipeline_id)
        run = await self._create_run(pipeline_id)
        step_outputs: dict[int, str] = {}
        failure: str | None = None

        for index, step in enumerate(definition.steps):
            request_id = _step_request_id(run.id, step.id)
            try:
                resolved_args = _resolve_args(step, step_outputs)
                node_script_id = await self._manual_node_script_id(step.node_id, step.script_id)
            except (DomainError, _PipelineRunFailure) as exc:
                failure = str(exc)
                await self._record_unexecuted_step(run.id, step, request_id, failure)
                await self._record_skipped_steps(run.id, definition.steps[index + 1 :])
                break

            run_step = await self._create_running_step(run.id, step, request_id, resolved_args)
            try:
                response = await self._script_execution_service.execute_node_script(
                    node_script_id,
                    args=resolved_args,
                    env=env or {},
                    timeout_seconds=timeout_seconds,
                    request_id=request_id,
                )
            except AgentClientError as exc:
                failure = str(exc)
                await self._finish_run_step_failed(run_step.id, failure)
                await self._record_skipped_steps(run.id, definition.steps[index + 1 :])
                break

            step_error = _response_error(response)
            await self._finish_run_step(run_step.id, response, step_error)
            if step_error is not None:
                failure = step_error
                await self._record_skipped_steps(run.id, definition.steps[index + 1 :])
                break

            step_outputs[step.id] = response.stdout

        await self._finish_run(run.id, failure)
        loaded_run = await self._session.get(PipelineRun, run.id)
        if loaded_run is None:
            raise NotFoundError(f"Pipeline run {run.id} not found")
        return loaded_run

    async def _load_definition(self, pipeline_id: int) -> _PipelineDefinition:
        pipeline = await self._session.get(Pipeline, pipeline_id)
        if pipeline is None:
            raise NotFoundError(f"Pipeline {pipeline_id} not found")

        step_result = await self._session.execute(
            select(PipelineStep)
            .where(PipelineStep.pipeline_id == pipeline_id)
            .order_by(PipelineStep.position)
        )
        steps = list(step_result.scalars().all())
        step_ids = [step.id for step in steps]

        args_by_step: dict[int, list[_ArgDefinition]] = {step_id: [] for step_id in step_ids}
        if step_ids:
            arg_result = await self._session.execute(
                select(PipelineStepArg)
                .where(PipelineStepArg.step_id.in_(step_ids))
                .order_by(PipelineStepArg.step_id, PipelineStepArg.arg_index)
            )
            for arg in arg_result.scalars().all():
                args_by_step[arg.step_id].append(
                    _ArgDefinition(
                        id=arg.id,
                        step_id=arg.step_id,
                        arg_index=arg.arg_index,
                        source_type=PipelineStepArgSourceType(arg.source_type),
                        literal_value=arg.literal_value,
                        source_step_id=arg.source_step_id,
                        json_field=arg.json_field,
                    )
                )

        definition_steps = [
            _StepDefinition(
                id=step.id,
                position=step.position,
                node_id=step.node_id,
                script_id=step.script_id,
                args=args_by_step[step.id],
            )
            for step in steps
        ]
        return _PipelineDefinition(pipeline_id=pipeline_id, steps=definition_steps)

    async def _create_run(self, pipeline_id: int) -> PipelineRun:
        now = await _current_sqlite_timestamp(self._session)
        run = PipelineRun(
            pipeline_id=pipeline_id,
            status=PipelineRunStatus.RUNNING.value,
            started_at=now,
            finished_at=None,
            error=None,
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def _manual_node_script_id(self, node_id: int, script_id: int) -> int:
        result = await self._session.execute(
            select(NodeScript.id).where(
                NodeScript.node_id == node_id,
                NodeScript.script_id == script_id,
                NodeScript.folder_id.is_(None),
                NodeScript.trigger_id.is_(None),
            )
        )
        node_script_id = result.scalar_one_or_none()
        if node_script_id is None:
            raise NotFoundError(f"Manual node-script link not found for node={node_id}, script={script_id}")
        return int(node_script_id)

    async def _create_running_step(
        self,
        run_id: int,
        step: _StepDefinition,
        request_id: UUID,
        resolved_args: list[str],
    ) -> PipelineRunStep:
        now = await _current_sqlite_timestamp(self._session)
        run_step = PipelineRunStep(
            pipeline_run_id=run_id,
            step_id=step.id,
            node_id=step.node_id,
            script_id=step.script_id,
            resolved_args=json.dumps(resolved_args),
            request_id=str(request_id),
            status=PipelineRunStepStatus.RUNNING.value,
            started_at=now,
            finished_at=None,
            exit_code=None,
            stdout=None,
            stderr=None,
            timed_out=False,
            error=None,
            duration_ms=None,
        )
        self._session.add(run_step)
        await self._session.commit()
        await self._session.refresh(run_step)
        return run_step

    async def _record_unexecuted_step(
        self,
        run_id: int,
        step: _StepDefinition,
        request_id: UUID,
        error: str,
    ) -> None:
        now = await _current_sqlite_timestamp(self._session)
        run_step = PipelineRunStep(
            pipeline_run_id=run_id,
            step_id=step.id,
            node_id=step.node_id,
            script_id=step.script_id,
            resolved_args="[]",
            request_id=str(request_id),
            status=PipelineRunStepStatus.FAILED.value,
            started_at=now,
            finished_at=now,
            exit_code=None,
            stdout=None,
            stderr=None,
            timed_out=False,
            error=error,
            duration_ms=None,
        )
        self._session.add(run_step)
        await self._session.commit()

    async def _finish_run_step(
        self,
        run_step_id: int,
        response: AgentScriptExecuteResponse,
        error: str | None,
    ) -> None:
        run_step = await self._load_run_step(run_step_id)
        run_step.status = (
            PipelineRunStepStatus.FAILED.value if error is not None else PipelineRunStepStatus.SUCCEEDED.value
        )
        run_step.finished_at = await _current_sqlite_timestamp(self._session)
        run_step.exit_code = response.exit_code
        run_step.stdout = response.stdout
        run_step.stderr = response.stderr
        run_step.timed_out = response.timed_out
        run_step.error = error
        run_step.duration_ms = response.duration_ms
        await self._session.commit()

    async def _finish_run_step_failed(self, run_step_id: int, error: str) -> None:
        run_step = await self._load_run_step(run_step_id)
        run_step.status = PipelineRunStepStatus.FAILED.value
        run_step.finished_at = await _current_sqlite_timestamp(self._session)
        run_step.error = error
        await self._session.commit()

    async def _record_skipped_steps(self, run_id: int, steps: list[_StepDefinition]) -> None:
        for step in steps:
            now = await _current_sqlite_timestamp(self._session)
            run_step = PipelineRunStep(
                pipeline_run_id=run_id,
                step_id=step.id,
                node_id=step.node_id,
                script_id=step.script_id,
                resolved_args="[]",
                request_id=str(_step_request_id(run_id, step.id)),
                status=PipelineRunStepStatus.SKIPPED.value,
                started_at=now,
                finished_at=now,
                exit_code=None,
                stdout=None,
                stderr=None,
                timed_out=False,
                error="skipped_after_step_failure",
                duration_ms=None,
            )
            self._session.add(run_step)
        await self._session.commit()

    async def _finish_run(self, run_id: int, error: str | None) -> None:
        run = await self._session.get(PipelineRun, run_id)
        if run is None:
            raise NotFoundError(f"Pipeline run {run_id} not found")
        run.status = PipelineRunStatus.FAILED.value if error is not None else PipelineRunStatus.SUCCEEDED.value
        run.finished_at = await _current_sqlite_timestamp(self._session)
        run.error = error
        await self._session.commit()
        await self._session.refresh(run)

    async def _load_run_step(self, run_step_id: int) -> PipelineRunStep:
        run_step = await self._session.get(PipelineRunStep, run_step_id)
        if run_step is None:
            raise NotFoundError(f"Pipeline run step {run_step_id} not found")
        return run_step


@dataclass(frozen=True)
class _PipelineDefinition:
    pipeline_id: int
    steps: list["_StepDefinition"]


@dataclass(frozen=True)
class _StepDefinition:
    id: int
    position: int
    node_id: int
    script_id: int
    args: list["_ArgDefinition"]


@dataclass(frozen=True)
class _ArgDefinition:
    id: int
    step_id: int
    arg_index: int
    source_type: PipelineStepArgSourceType
    literal_value: str | None
    source_step_id: int | None
    json_field: str | None


class _PipelineRunFailure(Exception):
    pass


def _resolve_args(step: _StepDefinition, step_outputs: dict[int, str]) -> list[str]:
    resolved: list[str] = []
    for arg in sorted(step.args, key=lambda item: item.arg_index):
        if arg.source_type == PipelineStepArgSourceType.LITERAL:
            resolved.append(arg.literal_value or "")
            continue

        if arg.source_step_id is None:
            raise _PipelineRunFailure("step_output arg requires source_step_id")
        if arg.json_field is None:
            raise _PipelineRunFailure("step_output arg requires json_field")
        source_stdout = step_outputs.get(arg.source_step_id)
        if source_stdout is None:
            raise _PipelineRunFailure(f"source step {arg.source_step_id} has no successful stdout")

        try:
            parsed = json.loads(source_stdout)
        except json.JSONDecodeError as exc:
            raise _PipelineRunFailure(f"source step {arg.source_step_id} stdout is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise _PipelineRunFailure(f"source step {arg.source_step_id} stdout is not a JSON object")
        if arg.json_field not in parsed:
            raise _PipelineRunFailure(f"json_field not found in source stdout: {arg.json_field}")
        value = parsed[arg.json_field]
        resolved.append(value if isinstance(value, str) else json.dumps(value))
    return resolved


def _response_error(response: AgentScriptExecuteResponse) -> str | None:
    if response.error_class is not None:
        return response.error_class
    if response.timed_out:
        return "timed_out"
    if response.exit_code != 0:
        return f"exit_code={response.exit_code}"
    return None


def _step_request_id(run_id: int, step_id: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"pipeline-run:{run_id}:step:{step_id}")


async def _current_sqlite_timestamp(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT datetime('now')"))
    return str(result.scalar_one())
