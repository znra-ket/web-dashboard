from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    ON_STARTUP = "on_startup"


class Trigger(Base):
    __tablename__ = "trigger"
    __table_args__ = (CheckConstraint("type IN ('schedule', 'on_startup')"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(nullable=False)


class TriggerSchedule(Base):
    __tablename__ = "trigger_schedule"

    trigger_id: Mapped[int] = mapped_column(
        ForeignKey("trigger.id", ondelete="CASCADE"),
        primary_key=True,
    )
    interval_seconds: Mapped[int] = mapped_column(nullable=False)


class TriggerOnStartup(Base):
    __tablename__ = "trigger_on_startup"

    trigger_id: Mapped[int] = mapped_column(
        ForeignKey("trigger.id", ondelete="CASCADE"),
        primary_key=True,
    )
