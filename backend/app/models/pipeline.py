from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PipelineStepArgSourceType(StrEnum):
    LITERAL = "literal"
    STEP_OUTPUT = "step_output"


class PipelineRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineRunStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Pipeline(Base):
    __tablename__ = "pipeline"
    __table_args__ = (
        CheckConstraint("archived IN (0, 1)"),
        Index("ux_pipeline_name_active", "name", unique=True, sqlite_where=text("archived = 0")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    archived: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))
    updated_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))


class PipelineStep(Base):
    __tablename__ = "pipeline_step"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "position"),
        CheckConstraint("position > 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(nullable=False)
    node_id: Mapped[int] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"))
    script_id: Mapped[int] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))


class PipelineStepArg(Base):
    __tablename__ = "pipeline_step_arg"
    __table_args__ = (
        UniqueConstraint("step_id", "arg_index"),
        CheckConstraint("arg_index >= 0"),
        CheckConstraint("source_type IN ('literal', 'step_output')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("pipeline_step.id", ondelete="CASCADE"))
    arg_index: Mapped[int] = mapped_column(nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    literal_value: Mapped[str | None] = mapped_column(Text)
    source_step_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_step.id", ondelete="RESTRICT"))
    json_field: Mapped[str | None] = mapped_column(String)


class PipelineRun(Base):
    __tablename__ = "pipeline_run"
    __table_args__ = (CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String)
    finished_at: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))


class PipelineRunStep(Base):
    __tablename__ = "pipeline_run_step"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "step_id"),
        CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')"),
        CheckConstraint("timed_out IN (0, 1)"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_run.id", ondelete="CASCADE"))
    step_id: Mapped[int] = mapped_column(nullable=False)
    node_id: Mapped[int] = mapped_column(nullable=False)
    script_id: Mapped[int] = mapped_column(nullable=False)
    resolved_args: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String)
    finished_at: Mapped[str | None] = mapped_column(String)
    exit_code: Mapped[int | None] = mapped_column()
    stdout: Mapped[str | None] = mapped_column(Text)
    stderr: Mapped[str | None] = mapped_column(Text)
    timed_out: Mapped[bool] = mapped_column(nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column()
