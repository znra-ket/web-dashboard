from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeHashGcStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


class NodeHashGc(Base):
    __tablename__ = "node_hash_gc"
    __table_args__ = (
        UniqueConstraint("node_id", "hash"),
        CheckConstraint("status IN ('pending', 'done', 'cancelled', 'failed')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"))
    hash: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=NodeHashGcStatus.PENDING.value)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_attempt_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))
    updated_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))
