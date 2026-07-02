from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trigger import Trigger, TriggerOnStartup, TriggerSchedule, TriggerType
from app.services.exceptions import NotFoundError, ValidationError


async def create_schedule_trigger(session: AsyncSession, interval_seconds: int) -> Trigger:
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
    await session.commit()
    await session.refresh(trigger)
    return trigger


async def create_on_startup_trigger(session: AsyncSession) -> Trigger:
    trigger = Trigger(type=TriggerType.ON_STARTUP.value)
    session.add(trigger)
    await session.flush()

    session.add(TriggerOnStartup(trigger_id=trigger.id))
    await session.commit()
    await session.refresh(trigger)
    return trigger


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
