from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeScript(Base):
    __tablename__ = "node_script"
    __table_args__ = (
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
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folder.id", ondelete="CASCADE"))
    trigger_id: Mapped[int | None] = mapped_column(ForeignKey("trigger.id", ondelete="RESTRICT"))
    last_run_at: Mapped[str | None] = mapped_column(String)
    last_success_at: Mapped[str | None] = mapped_column(String)
    last_error: Mapped[str | None] = mapped_column(String)
    last_duration_ms: Mapped[int | None] = mapped_column()
