"""Настройки из БД (панель /admin) + кеш; fallback на env (get_settings)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from models.app_setting import AppSetting

_CACHE_LOCK = asyncio.Lock()
_CACHE: dict[str, Any] | None = None
_CACHE_TS: float = 0.0
_TTL_SEC = 25.0

# Ключи в app_settings
K_TRIAL_HOURS = "trial_duration_hours"
K_TRIAL_MSG = "trial_message_limit"
K_SOFT_DAILY = "soft_daily_message_limit"
K_PAID_FB = "paid_fallback_daily_message_limit"
K_SUB_REMIND_DAYS = "subscription_reminder_days"
K_NOTIFY_NEW_USER = "notify_admins_new_user"
K_NOTIFY_PAYMENT = "notify_admins_payment"
K_NOTIFY_ERRORS = "notify_admins_errors"
K_WHITELIST_EXTRA = "whitelist_extra"


def invalidate_app_config_cache() -> None:
    global _CACHE, _CACHE_TS
    _CACHE = None
    _CACHE_TS = 0.0


async def _load_all(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(select(AppSetting))
    rows = result.scalars().all()
    return {r.key: r.value for r in rows}


async def get_all_cached(session: AsyncSession) -> dict[str, Any]:
    global _CACHE, _CACHE_TS
    async with _CACHE_LOCK:
        now = time.monotonic()
        if _CACHE is not None and now - _CACHE_TS < _TTL_SEC:
            return _CACHE
        _CACHE = await _load_all(session)
        _CACHE_TS = now
        return _CACHE


def _int_ov(data: dict[str, Any], key: str) -> int | None:
    row = data.get(key)
    if not row or "v" not in row:
        return None
    try:
        return int(row["v"])
    except (TypeError, ValueError):
        return None


def _bool_ov(data: dict[str, Any], key: str, default: bool) -> bool:
    row = data.get(key)
    if not row or "enabled" not in row:
        return default
    return bool(row["enabled"])


@dataclass(frozen=True)
class ProductLimits:
    trial_duration_hours: int
    trial_message_limit: int
    soft_daily_message_limit: int
    paid_fallback_daily_message_limit: int


@dataclass(frozen=True)
class NotifyConfig:
    subscription_reminder_days: int
    notify_admins_new_user: bool
    notify_admins_payment: bool
    notify_admins_errors: bool


async def load_product_limits(session: AsyncSession, settings: Settings | None = None) -> ProductLimits:
    settings = settings or get_settings()
    data = await get_all_cached(session)
    return ProductLimits(
        trial_duration_hours=_int_ov(data, K_TRIAL_HOURS) or settings.trial_duration_hours,
        trial_message_limit=_int_ov(data, K_TRIAL_MSG) or settings.trial_message_limit,
        soft_daily_message_limit=_int_ov(data, K_SOFT_DAILY) or settings.soft_daily_message_limit,
        paid_fallback_daily_message_limit=_int_ov(data, K_PAID_FB)
        or settings.paid_fallback_daily_message_limit,
    )


async def load_notify_config(session: AsyncSession, settings: Settings | None = None) -> NotifyConfig:
    settings = settings or get_settings()
    data = await get_all_cached(session)
    raw = _int_ov(data, K_SUB_REMIND_DAYS)
    if raw is None:
        days = 3
    else:
        days = max(0, min(30, raw))
    return NotifyConfig(
        subscription_reminder_days=days,
        notify_admins_new_user=_bool_ov(data, K_NOTIFY_NEW_USER, True),
        notify_admins_payment=_bool_ov(data, K_NOTIFY_PAYMENT, True),
        notify_admins_errors=_bool_ov(data, K_NOTIFY_ERRORS, True),
    )


async def get_whitelist_extra_ids(session: AsyncSession) -> set[int]:
    data = await get_all_cached(session)
    row = data.get(K_WHITELIST_EXTRA) or {}
    raw = row.get("ids") or []
    out: set[int] = set()
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


async def is_internal_access_allowed(
    user_id: int,
    settings: Settings,
    session: AsyncSession,
) -> bool:
    if not settings.internal_test_mode:
        return True
    if user_id in settings.internal_whitelist_id_set:
        return True
    extra = await get_whitelist_extra_ids(session)
    return user_id in extra


async def upsert_setting(session: AsyncSession, key: str, value: dict) -> None:
    row = await session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    await session.commit()
    invalidate_app_config_cache()
