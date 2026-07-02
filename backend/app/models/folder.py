from sqlalchemy import ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Folder(Base):
    __tablename__ = "folder"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))
    updated_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))


class FolderNode(Base):
    __tablename__ = "folder_node"
    __table_args__ = (UniqueConstraint("folder_id", "node_id"),)

    folder_id: Mapped[int] = mapped_column(
        ForeignKey("folder.id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id: Mapped[int] = mapped_column(
        ForeignKey("node.id", ondelete="CASCADE"),
        primary_key=True,
    )


class FolderScript(Base):
    __tablename__ = "folder_script"
    __table_args__ = (UniqueConstraint("folder_id", "script_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("folder.id", ondelete="CASCADE"))
    script_id: Mapped[int] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))
    trigger_id: Mapped[int | None] = mapped_column(ForeignKey("trigger.id", ondelete="RESTRICT"))
