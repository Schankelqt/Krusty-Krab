import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from core.config import Settings, get_settings
from core.database import SessionLocal
from services.metrics_aggregate import chunk_telegram_html, load_summary, summary_to_telegram_html

logger = logging.getLogger(__name__)


def seconds_until_next_report(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


async def send_daily_report(bot: Bot, settings: Settings) -> None:
    chat_id = settings.metrics_report_chat_id.strip()
    if not chat_id:
        return
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)
    async with SessionLocal() as session:
        m = await load_summary(session, since, now)
    text = summary_to_telegram_html(
        m,
        title=f"📊 Отчёт бота (последние 24 ч UTC, срез на {now:%Y-%m-%d %H:%M})",
    )
    cid = int(chat_id)
    for chunk in chunk_telegram_html(text):
        await bot.send_message(chat_id=cid, text=chunk)


async def metrics_reporter_loop(bot: Bot) -> None:
    settings = get_settings()
    if settings.metrics_report_on_start and settings.metrics_report_enabled:
        await asyncio.sleep(15)
        try:
            await send_daily_report(bot, get_settings())
        except Exception:
            logger.exception("initial metrics report failed")

    while True:
        try:
            settings = get_settings()
            delay = seconds_until_next_report(settings.metrics_report_hour_utc)
            await asyncio.sleep(delay)
            settings = get_settings()
            if not settings.metrics_report_enabled or not settings.metrics_report_chat_id.strip():
                await asyncio.sleep(300)
                continue
            await send_daily_report(bot, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("metrics reporter iteration failed")
            await asyncio.sleep(120)
