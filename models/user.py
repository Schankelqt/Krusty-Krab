from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram user id
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    plan: Mapped[str] = mapped_column(String(32), default="basic")
    # gpt | claude | gemini — после оплаты; пусто = глобальный PRIMARY_PROVIDER (например OpenClaw)
    billing_llm_line: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    openclaw_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Оплаченный биллинговый период: [subscription_period_start, subscription_period_end)
    subscription_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subscription_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_message_count: Mapped[int] = mapped_column(Integer, default=0)

    # Онбординг: false только у новых пользователей (в коде); в БД server_default true для старых строк
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
