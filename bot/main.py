import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from redis.asyncio import from_url as redis_from_url

from api.app import create_app
from bot.handlers import (
    admin,
    admin_grant_wizard,
    admin_panel,
    agent_settings,
    chat,
    client_guidance,
    orchestrator,
    start,
    system_errors,
)
from core.config import get_settings
from core.database import engine
from models import Base
from services.client_reminders import tick_subscription_reminders
from services.metrics_reporter import metrics_reporter_loop
from services import provisioning_service
from core.database import SessionLocal


_metrics_reporter_task: asyncio.Task[None] | None = None
_subscription_reminders_task: asyncio.Task[None] | None = None
_provisioning_worker_task: asyncio.Task[None] | None = None


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
            await asyncio.sleep(settings.subscription_reminder_interval_seconds)
            try:
                await tick_subscription_reminders(bot, redis_client)
            except Exception:
                log.exception("subscription reminder tick failed")
    finally:
        await redis_client.aclose()


async def _provisioning_worker_loop() -> None:
    settings = get_settings()
    log = logging.getLogger(__name__)
    interval_seconds = settings.provisioning_poll_interval_seconds

    log.info(
        "provision_worker loop_start interval_seconds=%s",
        interval_seconds,
    )

    while True:
        try:
            async with SessionLocal() as session:
                picked = await provisioning_service.run_next_job(session)
            if not picked:
                log.debug("provision_worker tick idle")
        except Exception:
            log.exception("provision_worker tick failed")
        await asyncio.sleep(interval_seconds)


def _ensure_background_tasks_started(bot: Bot, settings) -> None:
    global _metrics_reporter_task
    global _subscription_reminders_task
    global _provisioning_worker_task

    if settings.metrics_report_enabled and settings.metrics_report_chat_id.strip():
        if _metrics_reporter_task is None or _metrics_reporter_task.done():
            _metrics_reporter_task = asyncio.create_task(metrics_reporter_loop(bot), name="metrics_reporter")

    if _subscription_reminders_task is None or _subscription_reminders_task.done():
        _subscription_reminders_task = asyncio.create_task(
            _subscription_reminder_loop(bot), name="subscription_reminders"
        )

    if _provisioning_worker_task is None or _provisioning_worker_task.done():
        _provisioning_worker_task = asyncio.create_task(
            _provisioning_worker_loop(), name="provisioning_worker"
        )


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
    dp.include_router(client_guidance.router)
    dp.include_router(orchestrator.router)
    dp.include_router(chat.router)
    _ensure_background_tasks_started(bot, settings)
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
