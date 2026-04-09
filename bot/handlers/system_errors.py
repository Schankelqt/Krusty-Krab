import logging

from aiogram import Router
from aiogram.types import ErrorEvent

from services.team_notifications import notify_team_html

logger = logging.getLogger(__name__)

router = Router()


@router.error()
async def global_error_handler(event: ErrorEvent) -> bool:
    logger.exception("Unhandled handler error", exc_info=event.exception)
    try:
        await notify_team_html(
            f"Ошибка в обработчике:\n<pre>{str(event.exception)[:3500]}</pre>",
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
