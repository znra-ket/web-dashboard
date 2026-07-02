from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.node_script import NodeScript
from app.models.trigger import Trigger, TriggerOnStartup, TriggerSchedule, TriggerType
from app.services.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from app.services.scheduler_service import TriggerExecutionScheduler


async def create_schedule_trigger(session: AsyncSession, interval_seconds: int) -> Trigger:
    trigger = await _create_schedule_trigger(session, interval_seconds)
    await session.commit()
    await session.refresh(trigger)
    return trigger


async def create_on_startup_trigger(session: AsyncSession) -> Trigger:
    trigger = await _create_on_startup_trigger(session)
    await session.commit()
    await session.refresh(trigger)
    return trigger


async def set_schedule_trigger_on_node_script(
    session: AsyncSession,
    node_script_id: int,
    interval_seconds: int,
    scheduler: TriggerExecutionScheduler | None = None,
) -> NodeScript:
    node_script = await _read_node_script(session, node_script_id)
    trigger = await _create_schedule_trigger(session, interval_seconds)
    node_script.trigger_id = trigger.id
    await session.commit()
    await session.refresh(node_script)
    if scheduler is not None:
        scheduler.upsert_schedule_job(node_script.id, interval_seconds)
    return node_script


async def set_on_startup_trigger_on_node_script(
    session: AsyncSession,
    node_script_id: int,
    scheduler: TriggerExecutionScheduler | None = None,
) -> NodeScript:
    node_script = await _read_node_script(session, node_script_id)
    old_trigger_type = await _trigger_type(session, node_script.trigger_id)
    trigger = await _create_on_startup_trigger(session)
    node_script.trigger_id = trigger.id
    await session.commit()
    await session.refresh(node_script)
    if scheduler is not None and old_trigger_type == TriggerType.SCHEDULE.value:
        scheduler.remove_schedule_job(node_script.id)
    return node_script


async def update_schedule_trigger(
    session: AsyncSession,
    node_script_id: int,
    interval_seconds: int,
    scheduler: TriggerExecutionScheduler | None = None,
) -> NodeScript:
    if interval_seconds <= 0:
        raise ValidationError("Schedule trigger interval must be greater than 0")

    node_script = await _read_node_script(session, node_script_id)
    if node_script.trigger_id is None:
        raise NotFoundError(f"Schedule trigger for node-script {node_script_id} not found")

    schedule = await session.get(TriggerSchedule, node_script.trigger_id)
    if schedule is None:
        raise NotFoundError(f"Schedule trigger for node-script {node_script_id} not found")

    schedule.interval_seconds = interval_seconds
    await session.commit()
    await session.refresh(node_script)
    if scheduler is not None:
        scheduler.upsert_schedule_job(node_script.id, interval_seconds)
    return node_script


async def remove_trigger_from_node_script(
    session: AsyncSession,
    node_script_id: int,
    scheduler: TriggerExecutionScheduler | None = None,
) -> None:
    node_script = await _read_node_script(session, node_script_id)
    if node_script.trigger_id is None:
        return

    old_trigger_type = await _trigger_type(session, node_script.trigger_id)
    manual_duplicate = await _manual_presence_only_duplicate_exists(session, node_script)

    if manual_duplicate and node_script.folder_id is None:
        await session.execute(delete(NodeScript).where(NodeScript.id == node_script.id))
    else:
        node_script.trigger_id = None

    await session.commit()
    if scheduler is not None and old_trigger_type == TriggerType.SCHEDULE.value:
        scheduler.remove_schedule_job(node_script_id)


async def clone_trigger(session: AsyncSession, trigger_id: int) -> Trigger:
    source = await session.get(Trigger, trigger_id)
    if source is None:
        raise NotFoundError(f"Trigger {trigger_id} not found")

    clone = Trigger(type=source.type)
    session.add(clone)
    await session.flush()

    if source.type == TriggerType.SCHEDULE.value:
        source_schedule = await session.get(TriggerSchedule, trigger_id)
        if source_schedule is None:
            raise NotFoundError(f"Schedule config for trigger {trigger_id} not found")
        session.add(
            TriggerSchedule(
                trigger_id=clone.id,
                interval_seconds=source_schedule.interval_seconds,
            )
        )
    elif source.type == TriggerType.ON_STARTUP.value:
        source_on_startup = await session.get(TriggerOnStartup, trigger_id)
        if source_on_startup is None:
            raise NotFoundError(f"On-startup config for trigger {trigger_id} not found")
        session.add(TriggerOnStartup(trigger_id=clone.id))
    else:
        raise ValidationError(f"Unsupported trigger type: {source.type}")

    await session.flush()
    return clone


async def _create_schedule_trigger(session: AsyncSession, interval_seconds: int) -> Trigger:
    if interval_seconds <= 0:
        raise ValidationError("Schedule trigger interval must be greater than 0")

    trigger = Trigger(type=TriggerType.SCHEDULE.value)
    session.add(trigger)
    await session.flush()

    session.add(
        TriggerSchedule(
            trigger_id=trigger.id,
            interval_seconds=interval_seconds,
        )
    )
    await session.flush()
    return trigger


async def _create_on_startup_trigger(session: AsyncSession) -> Trigger:
    trigger = Trigger(type=TriggerType.ON_STARTUP.value)
    session.add(trigger)
    await session.flush()

    session.add(TriggerOnStartup(trigger_id=trigger.id))
    await session.flush()
    return trigger


async def _read_node_script(session: AsyncSession, node_script_id: int) -> NodeScript:
    node_script = await session.get(NodeScript, node_script_id)
    if node_script is None:
        raise NotFoundError(f"Node-script link {node_script_id} not found")
    return node_script


async def _trigger_type(session: AsyncSession, trigger_id: int | None) -> str | None:
    if trigger_id is None:
        return None
    trigger = await session.get(Trigger, trigger_id)
    return None if trigger is None else trigger.type


async def _manual_presence_only_duplicate_exists(
    session: AsyncSession,
    node_script: NodeScript,
) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    NodeScript.id != node_script.id,
                    NodeScript.node_id == node_script.node_id,
                    NodeScript.script_id == node_script.script_id,
                    NodeScript.folder_id.is_(None),
                    NodeScript.trigger_id.is_(None),
                )
            )
        )
    )
