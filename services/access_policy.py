"""Решение: триал / soft после триала / платный primary или fallback по токенам."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis

from core.config import Settings
from models.user import User
from services.app_config import ProductLimits
from services.billing_llm import resolve_primary_provider_for_paid_user
from services.limits_service import LimitsService
from services.usage_service import UsageService


@dataclass
class AccessDecision:
    allowed: bool
    deny_message: str | None
    provider_name: str
    increment_primary_daily: bool
    increment_trial: bool
    increment_soft_daily: bool
    increment_paid_fallback_daily: bool
    # Код отказа для метрик (если allowed=False)
    deny_reason: str | None = None


def paid_period_active(user: User, now: datetime) -> bool:
    if not user.is_active or user.subscription_period_start is None or user.subscription_period_end is None:
        return False
    return user.subscription_period_start <= now < user.subscription_period_end


def paid_period_boundaries_missing(user: User) -> bool:
    """Оплаченный флаг без дат периода — неконсистентное состояние (старые данные / ручные правки)."""
    return user.is_active and (
        user.subscription_period_start is None or user.subscription_period_end is None
    )


def _dt_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def paid_subscription_period_expired(user: User, now: datetime) -> bool:
    """Оплаченный флаг есть, даты заданы, конец периода уже прошёл (UTC)."""
    if not user.is_active or user.subscription_period_end is None:
        return False
    return now >= _dt_utc(user.subscription_period_end)


def paid_subscription_period_not_started(user: User, now: datetime) -> bool:
    """Начало периода в будущем (редко: сдвиг часов / отложенный старт по датам)."""
    if not user.is_active or user.subscription_period_start is None:
        return False
    if paid_subscription_period_expired(user, now):
        return False
    return now < _dt_utc(user.subscription_period_start)


def trial_active(user: User, pl: ProductLimits, now: datetime) -> bool:
    if user.is_active or user.trial_started_at is None:
        return False
    if user.trial_message_count >= pl.trial_message_limit:
        return False
    end = user.trial_started_at
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    trial_end = end + timedelta(hours=pl.trial_duration_hours)
    return now < trial_end


def _post_trial_soft_eligible(user: User, pl: ProductLimits, now: datetime) -> bool:
    if user.is_active:
        return False
    if user.trial_started_at is None:
        return False
    return not trial_active(user, pl, now)


async def resolve_chat_access(
    *,
    user: User,
    settings: Settings,
    product_limits: ProductLimits,
    now: datetime,
    usage_service: UsageService,
    limits: LimitsService,
) -> AccessDecision:
    if settings.admin_skip_llm_limits and user.id in settings.admin_id_set:
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=settings.provider_for_admin_skip_limits(),
            increment_primary_daily=False,
            increment_trial=False,
            increment_soft_daily=False,
            increment_paid_fallback_daily=False,
            deny_reason=None,
        )

    if paid_period_active(user, now):
        start = user.subscription_period_start
        end = user.subscription_period_end
        assert start is not None and end is not None
        used = await usage_service.get_metered_tokens_in_period(
            user.id, start, end, providers=settings.metering_primary_providers
        )
        token_limit = settings.paid_token_limit_for_plan(user.plan)
        if used >= token_limit:
            if not await limits.can_paid_fallback(user.id):
                return AccessDecision(
                    allowed=False,
                    deny_message="Лимит токенов на период исчерпан, а дневной лимит экономичного режима (Ollama) тоже достигнут. Попробуйте завтра или продлите тариф.",
                    provider_name=settings.fallback_provider,
                    increment_primary_daily=False,
                    increment_trial=False,
                    increment_soft_daily=False,
                    increment_paid_fallback_daily=False,
                    deny_reason="paid_fallback_daily_cap",
                )
            return AccessDecision(
                allowed=True,
                deny_message=None,
                provider_name=settings.fallback_provider,
                increment_primary_daily=False,
                increment_trial=False,
                increment_soft_daily=False,
                increment_paid_fallback_daily=True,
                deny_reason=None,
            )
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=resolve_primary_provider_for_paid_user(user, settings),
            increment_primary_daily=False,
            increment_trial=False,
            increment_soft_daily=False,
            increment_paid_fallback_daily=False,
            deny_reason=None,
        )

    if user.is_active and not paid_period_active(user, now):
        if not await limits.can_soft_daily(user.id):
            return AccessDecision(
                allowed=False,
                deny_message="Оплаченный период завершён. Лимит бесплатных ответов на сегодня исчерпан. Продлите подписку.",
                provider_name=settings.fallback_provider,
                increment_primary_daily=False,
                increment_trial=False,
                increment_soft_daily=False,
                increment_paid_fallback_daily=False,
                deny_reason="soft_after_paid_exhausted",
            )
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=settings.fallback_provider,
            increment_primary_daily=False,
            increment_trial=False,
            increment_soft_daily=True,
            increment_paid_fallback_daily=False,
            deny_reason=None,
        )

    if trial_active(user, product_limits, now):
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=settings.trial_provider,
            increment_primary_daily=False,
            increment_trial=True,
            increment_soft_daily=False,
            increment_paid_fallback_daily=False,
            deny_reason=None,
        )

    if _post_trial_soft_eligible(user, product_limits, now):
        if not await limits.can_soft_daily(user.id):
            return AccessDecision(
                allowed=False,
                deny_message="Лимит бесплатных ответов на сегодня исчерпан. Оформите подписку для полного доступа.",
                provider_name=settings.fallback_provider,
                increment_primary_daily=False,
                increment_trial=False,
                increment_soft_daily=False,
                increment_paid_fallback_daily=False,
                deny_reason="soft_post_trial_exhausted",
            )
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=settings.fallback_provider,
            increment_primary_daily=False,
            increment_trial=False,
            increment_soft_daily=True,
            increment_paid_fallback_daily=False,
            deny_reason=None,
        )

    return AccessDecision(
        allowed=False,
        deny_message='Нажмите «Познакомиться с OpenClaw» для триала или «Тарифы и оплата» для подписки.',
        provider_name=settings.fallback_provider,
        increment_primary_daily=False,
        increment_trial=False,
        increment_soft_daily=False,
        increment_paid_fallback_daily=False,
        deny_reason="need_cta_trial_or_subscribe",
    )


async def maybe_send_token_warnings(
    *,
    redis: Redis,
    user: User,
    settings: Settings,
    used_before: int,
    used_after: int,
    send_message: Callable[[str], Awaitable[None]],
) -> list[str]:
    """Отправляет предупреждения о токенах; возвращает ключи сработавших порогов для метрик."""
    fired: list[str] = []
    if user.subscription_period_start is None:
        return fired
    limit = settings.paid_token_limit_for_plan(user.plan)
    if limit <= 0:
        return fired
    remaining_after = limit - used_after
    period_tag = str(int(user.subscription_period_start.timestamp()))

    if remaining_after <= int(limit * 0.20) and (limit - used_before) > int(limit * 0.20):
        key = f"tokwarn:20:{user.id}:{period_tag}"
        if not await redis.get(key):
            await redis.set(key, "1", ex=90 * 86400)
            await send_message(
                f"⚠️ Осталось меньше 20% токенов на период: ~{max(0, remaining_after):,} из {limit:,}."
            )
            fired.append("token_warn_20pct")

    if remaining_after <= int(limit * 0.05) and (limit - used_before) > int(limit * 0.05):
        key = f"tokwarn:5:{user.id}:{period_tag}"
        if not await redis.get(key):
            await redis.set(key, "1", ex=90 * 86400)
            await send_message(
                f"🔻 Осталось меньше 5% токенов на период: ~{max(0, remaining_after):,} из {limit:,}. "
                "Далее включится экономичный режим (Ollama) с дневным лимитом."
            )
            fired.append("token_warn_5pct")
    return fired
