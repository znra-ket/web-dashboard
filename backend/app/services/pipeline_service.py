from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import Pipeline, PipelineStep, PipelineStepArg, PipelineStepArgSourceType
from app.schemas.pipeline import (
    PipelineCreate,
    PipelineStepArgCreate,
    PipelineStepArgUpdate,
    PipelineStepCreate,
    PipelineStepUpdate,
    PipelineUpdate,
)
from app.services.exceptions import ConflictError, NotFoundError, ValidationError


async def create_pipeline(session: AsyncSession, data: PipelineCreate) -> Pipeline:
    pipeline = Pipeline(name=data.name, archived=False)
    session.add(pipeline)
    return await _commit_or_conflict(session, pipeline, f"Active pipeline name already exists: {data.name}")


async def read_pipeline(session: AsyncSession, pipeline_id: int) -> Pipeline:
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise NotFoundError(f"Pipeline {pipeline_id} not found")
    return pipeline


async def list_pipelines(session: AsyncSession, include_archived: bool = False) -> list[Pipeline]:
    query = select(Pipeline).order_by(Pipeline.id)
    if not include_archived:
        query = query.where(Pipeline.archived.is_(False))
    result = await session.execute(query)
    return list(result.scalars().all())


async def update_pipeline(session: AsyncSession, pipeline_id: int, data: PipelineUpdate) -> Pipeline:
    pipeline = await read_pipeline(session, pipeline_id)
    pipeline.name = data.name
    pipeline.updated_at = await _current_sqlite_timestamp(session)
    return await _commit_or_conflict(session, pipeline, f"Active pipeline name already exists: {data.name}")


async def archive_pipeline(session: AsyncSession, pipeline_id: int) -> Pipeline:
    pipeline = await read_pipeline(session, pipeline_id)
    pipeline.archived = True
    pipeline.updated_at = await _current_sqlite_timestamp(session)
    await session.commit()
    await session.refresh(pipeline)
    return pipeline


async def create_pipeline_step(
    session: AsyncSession,
    pipeline_id: int,
    data: PipelineStepCreate,
) -> PipelineStep:
    await _ensure_pipeline_exists(session, pipeline_id)
    step = PipelineStep(
        pipeline_id=pipeline_id,
        position=data.position,
        node_id=data.node_id,
        script_id=data.script_id,
    )
    session.add(step)
    return await _commit_or_conflict(session, step, "Pipeline step position already exists")


async def read_pipeline_step(session: AsyncSession, step_id: int) -> PipelineStep:
    step = await session.get(PipelineStep, step_id)
    if step is None:
        raise NotFoundError(f"Pipeline step {step_id} not found")
    return step


async def list_pipeline_steps(session: AsyncSession, pipeline_id: int) -> list[PipelineStep]:
    await _ensure_pipeline_exists(session, pipeline_id)
    result = await session.execute(
        select(PipelineStep)
        .where(PipelineStep.pipeline_id == pipeline_id)
        .order_by(PipelineStep.position)
    )
    return list(result.scalars().all())


async def update_pipeline_step(
    session: AsyncSession,
    step_id: int,
    data: PipelineStepUpdate,
) -> PipelineStep:
    step = await read_pipeline_step(session, step_id)
    step.position = data.position
    step.node_id = data.node_id
    step.script_id = data.script_id
    try:
        await _validate_pipeline_args(session, step.pipeline_id)
    except ValidationError:
        await session.rollback()
        raise
    return await _commit_or_conflict(session, step, "Pipeline step position already exists")


async def delete_pipeline_step(session: AsyncSession, step_id: int) -> None:
    step = await read_pipeline_step(session, step_id)
    await session.delete(step)
    await session.commit()


async def create_pipeline_step_arg(
    session: AsyncSession,
    step_id: int,
    data: PipelineStepArgCreate,
) -> PipelineStepArg:
    step = await read_pipeline_step(session, step_id)
    await _validate_step_arg(session, step, data)
    arg = PipelineStepArg(
        step_id=step_id,
        arg_index=data.arg_index,
        source_type=data.source_type.value,
        literal_value=data.literal_value,
        source_step_id=data.source_step_id,
        json_field=data.json_field,
    )
    session.add(arg)
    return await _commit_or_conflict(session, arg, "Pipeline step arg index already exists")


async def list_pipeline_step_args(session: AsyncSession, step_id: int) -> list[PipelineStepArg]:
    await read_pipeline_step(session, step_id)
    result = await session.execute(
        select(PipelineStepArg)
        .where(PipelineStepArg.step_id == step_id)
        .order_by(PipelineStepArg.arg_index)
    )
    return list(result.scalars().all())


async def update_pipeline_step_arg(
    session: AsyncSession,
    arg_id: int,
    data: PipelineStepArgUpdate,
) -> PipelineStepArg:
    arg = await session.get(PipelineStepArg, arg_id)
    if arg is None:
        raise NotFoundError(f"Pipeline step arg {arg_id} not found")
    step = await read_pipeline_step(session, arg.step_id)
    await _validate_step_arg(session, step, data)
    arg.arg_index = data.arg_index
    arg.source_type = data.source_type.value
    arg.literal_value = data.literal_value
    arg.source_step_id = data.source_step_id
    arg.json_field = data.json_field
    return await _commit_or_conflict(session, arg, "Pipeline step arg index already exists")


async def delete_pipeline_step_arg(session: AsyncSession, arg_id: int) -> None:
    arg = await session.get(PipelineStepArg, arg_id)
    if arg is None:
        raise NotFoundError(f"Pipeline step arg {arg_id} not found")
    await session.delete(arg)
    await session.commit()


async def _ensure_pipeline_exists(session: AsyncSession, pipeline_id: int) -> None:
    await read_pipeline(session, pipeline_id)


async def _validate_step_arg(
    session: AsyncSession,
    step: PipelineStep,
    data: PipelineStepArgCreate | PipelineStepArgUpdate,
) -> None:
    if data.source_type == PipelineStepArgSourceType.LITERAL:
        if data.source_step_id is not None:
            raise ValidationError("Literal pipeline arg cannot reference a source step")
        return

    if data.source_step_id is None:
        raise ValidationError("step_output pipeline arg requires source_step_id")

    source_step = await session.get(PipelineStep, data.source_step_id)
    if source_step is None:
        raise NotFoundError(f"Source pipeline step {data.source_step_id} not found")
    if source_step.pipeline_id != step.pipeline_id:
        raise ValidationError("source_step_id must belong to the same pipeline")
    if source_step.position >= step.position:
        raise ValidationError("source_step_id must reference a previous pipeline step")


async def _validate_pipeline_args(session: AsyncSession, pipeline_id: int) -> None:
    result = await session.execute(
        select(PipelineStepArg, PipelineStep)
        .join(PipelineStep, PipelineStep.id == PipelineStepArg.step_id)
        .where(PipelineStep.pipeline_id == pipeline_id)
    )
    for arg, step in result.all():
        data = PipelineStepArgUpdate(
            arg_index=arg.arg_index,
            source_type=PipelineStepArgSourceType(arg.source_type),
            literal_value=arg.literal_value,
            source_step_id=arg.source_step_id,
            json_field=arg.json_field,
        )
        await _validate_step_arg(session, step, data)


async def _commit_or_conflict(session: AsyncSession, instance, message: str):  # noqa: ANN001
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(message) from exc

    await session.refresh(instance)
    return instance


async def _current_sqlite_timestamp(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT datetime('now')"))
    return str(result.scalar_one())
