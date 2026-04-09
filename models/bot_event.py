from sqlalchemy import BigInteger, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class BotEvent(Base, TimestampMixin):
    """События для метрик и отчётности (append-only)."""

    __tablename__ = "bot_events"
    __table_args__ = (
        Index("ix_bot_events_created_at", "created_at"),
        Index("ix_bot_events_event_type_created", "event_type", "created_at"),
        Index("ix_bot_events_user_id_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
