from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trigger import Trigger, TriggerOnStartup, TriggerSchedule, TriggerType
from app.services.exceptions import ValidationError


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
