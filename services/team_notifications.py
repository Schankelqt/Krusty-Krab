"""Уведомления команде (админы / отдельный чат)."""

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from core.config import Settings, get_settings
from core.database import SessionLocal
from services.app_config import load_notify_config

logger = logging.getLogger(__name__)


async def notify_team_html(
    text: str,
    *,
    settings: Settings | None = None,
    kind: str = "generic",
) -> None:
    """
    kind: user | payment | error | generic — проверяет флаги в app_settings.
    """
    settings = settings or get_settings()
    async with SessionLocal() as session:
        nc = await load_notify_config(session, settings)
        if kind == "user" and not nc.notify_admins_new_user:
            return
        if kind == "payment" and not nc.notify_admins_payment:
            return
        if kind == "error" and not nc.notify_admins_errors:
            return

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        chat = (settings.admin_team_chat_id or "").strip()
        if chat:
            await bot.send_message(chat_id=int(chat), text=f"🔔 <b>Команда</b>\n{text}")
        else:
            for aid in settings.admin_id_set:
                try:
                    await bot.send_message(chat_id=aid, text=f"🔔 <b>Бот</b>\n{text}")
                except Exception:
                    logger.exception("Failed to notify admin %s", aid)
    finally:
        await bot.session.close()
