from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class AssistantInstance(Base, TimestampMixin):
    __tablename__ = "assistant_instances"
    __table_args__ = (
        CheckConstraint(
            "route_mode IN ('paid_api', 'free_ollama', 'auto')",
            name="ck_assistant_instances_route_mode",
        ),
        CheckConstraint(
            "status IN ('draft', 'provisioning', 'ready', 'failed', 'archived')",
            name="ck_assistant_instances_status",
        ),
        Index("ix_assistant_instances_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(512), nullable=False)
    goal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    route_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    telegram_bot_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
