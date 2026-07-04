from backend.app.architecture.constants import NODE_LIFECYCLE_STATES_V1, TRIGGER_TYPES_V1
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Base(DeclarativeBase):
    pass


class Node(Base):
    __tablename__ = "node"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_quoted(NODE_LIFECYCLE_STATES_V1)})",
            name="ck_node_status_v1",
        ),
        CheckConstraint("port > 0 AND port <= 65535", name="ck_node_port_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    host: Mapped[str]
    port: Mapped[int] = mapped_column(default=443)
    status: Mapped[str]
    created_at: Mapped[str]
    updated_at: Mapped[str]


class NodeMTLSIdentity(Base):
    __tablename__ = "node_mtls_identity"

    node_id: Mapped[int] = mapped_column(
        ForeignKey("node.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_cert_fingerprint: Mapped[str] = mapped_column(unique=True)
    agent_public_key_fingerprint: Mapped[str | None]
    agent_cert_serial: Mapped[str | None]
    issued_at: Mapped[str | None]
    expires_at: Mapped[str | None]
    created_at: Mapped[str]


class NodeBootstrapState(Base):
    __tablename__ = "node_bootstrap_state"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'closed', 'expired')",
            name="ck_node_bootstrap_state_status",
        ),
    )

    node_id: Mapped[int] = mapped_column(
        ForeignKey("node.id", ondelete="CASCADE"),
        primary_key=True,
    )
    token_hash: Mapped[str]
    expires_at: Mapped[str]
    absolute_expires_at: Mapped[str]
    status: Mapped[str]
    created_at: Mapped[str]
    updated_at: Mapped[str]


class Script(Base):
    __tablename__ = "script"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    content: Mapped[str]
    current_hash: Mapped[str]
    created_at: Mapped[str]
    updated_at: Mapped[str]


class Folder(Base):
    __tablename__ = "folder"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[str]
    updated_at: Mapped[str]


class Trigger(Base):
    __tablename__ = "trigger"
    __table_args__ = (
        CheckConstraint(
            f"type IN ({_quoted(TRIGGER_TYPES_V1)})",
            name="ck_trigger_type_v1",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]
    created_at: Mapped[str]


class TriggerSchedule(Base):
    __tablename__ = "trigger_schedule"
    __table_args__ = (
        CheckConstraint("interval_seconds > 0", name="ck_trigger_schedule_interval"),
    )

    trigger_id: Mapped[int] = mapped_column(
        ForeignKey("trigger.id", ondelete="CASCADE"),
        primary_key=True,
    )
    interval_seconds: Mapped[int]


class TriggerOnStartup(Base):
    __tablename__ = "trigger_on_startup"

    trigger_id: Mapped[int] = mapped_column(
        ForeignKey("trigger.id", ondelete="CASCADE"),
        primary_key=True,
    )


class FolderNode(Base):
    __tablename__ = "folder_node"

    folder_id: Mapped[int] = mapped_column(
        ForeignKey("folder.id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id: Mapped[int] = mapped_column(
        ForeignKey("node.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[str]


class FolderScript(Base):
    __tablename__ = "folder_script"

    folder_id: Mapped[int] = mapped_column(
        ForeignKey("folder.id", ondelete="CASCADE"),
        primary_key=True,
    )
    script_id: Mapped[int] = mapped_column(
        ForeignKey("script.id", ondelete="CASCADE"),
        primary_key=True,
    )
    trigger_id: Mapped[int | None] = mapped_column(
        ForeignKey("trigger.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[str]


class NodeScript(Base):
    __tablename__ = "node_script"
    __table_args__ = (
        CheckConstraint(
            "last_run_status IS NULL OR last_run_status IN "
            "('success', 'failed', 'timeout', 'transport_error')",
            name="ck_node_script_last_run_status",
        ),
        Index(
            "ux_node_script_folder",
            "node_id",
            "script_id",
            "folder_id",
            unique=True,
            sqlite_where=text("folder_id IS NOT NULL"),
        ),
        Index(
            "ux_node_script_manual_no_trigger",
            "node_id",
            "script_id",
            unique=True,
            sqlite_where=text("folder_id IS NULL AND trigger_id IS NULL"),
        ),
        Index(
            "ux_node_script_manual_with_trigger",
            "node_id",
            "script_id",
            "trigger_id",
            unique=True,
            sqlite_where=text("folder_id IS NULL AND trigger_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"))
    script_id: Mapped[int] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folder.id", ondelete="RESTRICT"),
    )
    trigger_id: Mapped[int | None] = mapped_column(
        ForeignKey("trigger.id", ondelete="RESTRICT"),
    )
    last_run_status: Mapped[str | None]
    last_run_at: Mapped[str | None]
    last_run_request_id: Mapped[str | None]
    last_run_error: Mapped[str | None]
    created_at: Mapped[str]
    updated_at: Mapped[str]


class NodeHashGC(Base):
    __tablename__ = "node_hash_gc"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('script_deleted', 'script_updated', 'binding_removed')",
            name="ck_node_hash_gc_reason",
        ),
        CheckConstraint(
            "status IN ('pending', 'done', 'cancelled', 'failed')",
            name="ck_node_hash_gc_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_node_hash_gc_attempts"),
        UniqueConstraint("node_id", "hash", name="uq_node_hash_gc_node_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"))
    hash: Mapped[str]
    reason: Mapped[str]
    status: Mapped[str]
    attempts: Mapped[int]
    created_at: Mapped[str]
    last_attempt_at: Mapped[str | None]


class Pipeline(Base):
    __tablename__ = "pipeline"
    __table_args__ = (
        CheckConstraint("archived IN (0, 1)", name="ck_pipeline_archived"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    archived: Mapped[int]
    created_at: Mapped[str]
    updated_at: Mapped[str]


class PipelineStep(Base):
    __tablename__ = "pipeline_step"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_pipeline_step_position"),
        UniqueConstraint("pipeline_id", "position", name="uq_pipeline_step_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline.id", ondelete="CASCADE"),
    )
    position: Mapped[int]
    node_id: Mapped[int] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"))
    script_id: Mapped[int] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))
    created_at: Mapped[str]


class PipelineStepArg(Base):
    __tablename__ = "pipeline_step_arg"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('static', 'step_output')",
            name="ck_pipeline_step_arg_source_type",
        ),
        UniqueConstraint("step_id", "name", name="uq_pipeline_step_arg_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_step.id", ondelete="CASCADE"),
    )
    name: Mapped[str]
    source_type: Mapped[str]
    static_value: Mapped[str | None]
    source_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_step.id", ondelete="CASCADE"),
    )
    source_json_path: Mapped[str | None]


class PipelineRun(Base):
    __tablename__ = "pipeline_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'cancelled')",
            name="ck_pipeline_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline.id", ondelete="RESTRICT"),
    )
    status: Mapped[str]
    started_at: Mapped[str]
    finished_at: Mapped[str | None]


class PipelineRunStep(Base):
    __tablename__ = "pipeline_run_step"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', 'skipped')",
            name="ck_pipeline_run_step_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_run.id", ondelete="CASCADE"))
    step_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_step.id", ondelete="SET NULL"),
    )
    step_position: Mapped[int]
    node_id_snapshot: Mapped[int]
    script_id_snapshot: Mapped[int]
    script_name_snapshot: Mapped[str]
    script_hash_snapshot: Mapped[str]
    resolved_args_json: Mapped[str]
    status: Mapped[str]
    stdout: Mapped[str | None]
    stderr: Mapped[str | None]
    exit_code: Mapped[int | None]
    error_class: Mapped[str | None]
    started_at: Mapped[str | None]
    finished_at: Mapped[str | None]
