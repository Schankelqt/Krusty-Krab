import logging
import re

from aiogram import Router
from aiogram.types import ErrorEvent

from services.team_notifications import notify_team_html

logger = logging.getLogger(__name__)
_GENERIC_ERROR_MESSAGE = "Internal error"
_SENSITIVE_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
)

router = Router()


def _sanitize_error_text(exc: Exception) -> str:
    raw = str(exc or "").strip()
    if not raw:
        return _GENERIC_ERROR_MESSAGE
    redacted = raw
    for pattern in _SENSITIVE_ERROR_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    redacted = redacted[:500]
    return redacted or _GENERIC_ERROR_MESSAGE


@router.error()
async def global_error_handler(event: ErrorEvent) -> bool:
    safe_error = _sanitize_error_text(event.exception)
    logger.error("Unhandled handler error: %s", safe_error)
    try:
        await notify_team_html(
            f"Ошибка в обработчике:\n<pre>{safe_error}</pre>",
            kind="error",
        )
    except Exception:
        logger.exception("Failed to notify team about error")
    if event.update is None:
        return True
    msg = event.update.message
    if msg is None and event.update.callback_query:
        msg = event.update.callback_query.message
    if msg:
        try:
            await msg.answer(
                "Произошла внутренняя ошибка. Мы уже получили уведомление. "
                "Попробуйте ещё раз через минуту или напишите /start."
            )
        except Exception:
            pass
    return True
