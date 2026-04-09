"""Связь оплаченной линии моделей (gpt / claude / gemini) с провайдером LLM в роутере."""

from core.config import Settings
from models.user import User


def resolve_primary_provider_for_paid_user(user: User, settings: Settings) -> str:
    """
    После оплаты в `billing_llm_line` хранится линия API.
    Если пусто — используется глобальный PRIMARY_PROVIDER (OpenClaw, mock, openai и т.д.).
    """
    line = (user.billing_llm_line or "").strip().lower()
    if line == "gpt":
        return "openai"
    if line == "claude":
        return "anthropic"
    if line == "gemini":
        return "gemini"
    return settings.primary_provider
