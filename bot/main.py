import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from redis.asyncio import from_url as redis_from_url

from api.app import create_app
from bot.handlers import admin, admin_grant_wizard, admin_panel, agent_settings, chat, start, system_errors
from core.config import get_settings
from core.database import engine
from models import Base
from services.client_reminders import tick_subscription_reminders
from services.metrics_reporter import metrics_reporter_loop


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _subscription_reminder_loop(bot: Bot) -> None:
    settings = get_settings()
    log = logging.getLogger(__name__)
    redis_client = redis_from_url(settings.redis_url, decode_responses=True)
    try:
        try:
            await tick_subscription_reminders(bot, redis_client)
        except Exception:
            log.exception("subscription reminder initial tick failed")
        while True:
            await asyncio.sleep(3600)
            try:
                await tick_subscription_reminders(bot, redis_client)
            except Exception:
                log.exception("subscription reminder tick failed")
    finally:
        await redis_client.aclose()


async def run_bot() -> None:
    settings = get_settings()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)
    dp.include_router(system_errors.router)
    dp.include_router(admin.router)
    dp.include_router(admin_grant_wizard.router)
    dp.include_router(admin_panel.router)
    dp.include_router(agent_settings.router)
    dp.include_router(start.router)
    dp.include_router(chat.router)
    if settings.metrics_report_enabled and settings.metrics_report_chat_id.strip():
        asyncio.create_task(metrics_reporter_loop(bot), name="metrics_reporter")
    asyncio.create_task(_subscription_reminder_loop(bot), name="subscription_reminders")
    await dp.start_polling(bot)


async def run_api() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        create_app(),
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await init_db()
    settings = get_settings()
    if settings.billing_http_enabled:
        await asyncio.gather(run_bot(), run_api())
    else:
        await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
