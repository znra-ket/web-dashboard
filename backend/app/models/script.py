from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Script(Base):
    __tablename__ = "script"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    current_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))
    updated_at: Mapped[str] = mapped_column(String, server_default=text("(datetime('now'))"))
