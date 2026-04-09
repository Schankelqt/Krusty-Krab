"""Напоминания клиентам о скором окончании оплаченного периода."""

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from redis.asyncio import Redis
from sqlalchemy import select

from core.config import get_settings
from core.database import SessionLocal
from models.user import User
from services.access_policy import paid_period_active
from services.app_config import load_notify_config

logger = logging.getLogger(__name__)


async def tick_subscription_reminders(bot: Bot, redis: Redis) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        nc = await load_notify_config(session, settings)
        days = nc.subscription_reminder_days
        if days <= 0:
            return

        now = datetime.now(timezone.utc)
        until = now + timedelta(days=days)
        stmt = select(User).where(
            User.is_active.is_(True),
            User.subscription_period_end.isnot(None),
            User.subscription_period_end > now,
            User.subscription_period_end <= until,
        )
        rows = (await session.execute(stmt)).scalars().all()

    for user in rows:
        if not paid_period_active(user, datetime.now(timezone.utc)):
            continue
        assert user.subscription_period_end is not None
        end = user.subscription_period_end
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        tag = str(int(end.timestamp()))
        key = f"subrem:{user.id}:{tag}"
        if await redis.get(key):
            continue
        text = (
            "📅 <b>Напоминание</b>\n"
            f"Оплаченный период заканчивается: <b>{end:%d.%m.%Y %H:%M} UTC</b>.\n"
            "Продлите подписку через «Тарифы и оплата», чтобы не потерять доступ к полной модели."
        )
        try:
            await bot.send_message(chat_id=user.id, text=text)
            await redis.set(key, "1", ex=60 * 86400)
        except Exception:
            logger.exception("subscription reminder failed user=%s", user.id)
