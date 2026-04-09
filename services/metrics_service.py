import logging
from typing import Any

from core.config import get_settings
from core.database import SessionLocal
from models.bot_event import BotEvent

logger = logging.getLogger(__name__)


async def record_event(
    event_type: str,
    *,
    user_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Записывает событие метрик; при ошибке не бросает наружу (не ломает основной флоу)."""
    settings = get_settings()
    if not settings.metrics_enabled:
        return
    et = (event_type or "unknown")[:64]
    try:
        async with SessionLocal() as session:
            session.add(BotEvent(event_type=et, user_id=user_id, payload=payload))
            await session.commit()
    except Exception:
        logger.exception("metrics record failed event_type=%s", et)
