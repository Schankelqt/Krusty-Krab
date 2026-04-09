"""Решение: триал / soft после триала / платный primary или fallback по токенам."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis

from core.config import Settings
from models.user import User
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


def paid_period_active(user: User, now: datetime) -> bool:
    if not user.is_active or user.subscription_period_start is None or user.subscription_period_end is None:
        return False
    return user.subscription_period_start <= now < user.subscription_period_end


def trial_active(user: User, settings: Settings, now: datetime) -> bool:
    if user.is_active or user.trial_started_at is None:
        return False
    if user.trial_message_count >= settings.trial_message_limit:
        return False
    end = user.trial_started_at
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    trial_end = end + timedelta(hours=settings.trial_duration_hours)
    return now < trial_end


def _post_trial_soft_eligible(user: User, settings: Settings, now: datetime) -> bool:
    if user.is_active:
        return False
    if user.trial_started_at is None:
        return False
    return not trial_active(user, settings, now)


async def resolve_chat_access(
    *,
    user: User,
    settings: Settings,
    now: datetime,
    usage_service: UsageService,
    limits: LimitsService,
) -> AccessDecision:
    if paid_period_active(user, now):
        start = user.subscription_period_start
        end = user.subscription_period_end
        assert start is not None and end is not None
        used = await usage_service.get_user_tokens_in_period(user.id, start, end)
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
                )
            return AccessDecision(
                allowed=True,
                deny_message=None,
                provider_name=settings.fallback_provider,
                increment_primary_daily=False,
                increment_trial=False,
                increment_soft_daily=False,
                increment_paid_fallback_daily=True,
            )
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=resolve_primary_provider_for_paid_user(user, settings),
            increment_primary_daily=False,
            increment_trial=False,
            increment_soft_daily=False,
            increment_paid_fallback_daily=False,
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
            )
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=settings.fallback_provider,
            increment_primary_daily=False,
            increment_trial=False,
            increment_soft_daily=True,
            increment_paid_fallback_daily=False,
        )

    if trial_active(user, settings, now):
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=settings.trial_provider,
            increment_primary_daily=False,
            increment_trial=True,
            increment_soft_daily=False,
            increment_paid_fallback_daily=False,
        )

    if _post_trial_soft_eligible(user, settings, now):
        if not await limits.can_soft_daily(user.id):
            return AccessDecision(
                allowed=False,
                deny_message="Лимит бесплатных ответов на сегодня исчерпан. Оформите подписку для полного доступа.",
                provider_name=settings.fallback_provider,
                increment_primary_daily=False,
                increment_trial=False,
                increment_soft_daily=False,
                increment_paid_fallback_daily=False,
            )
        return AccessDecision(
            allowed=True,
            deny_message=None,
            provider_name=settings.fallback_provider,
            increment_primary_daily=False,
            increment_trial=False,
            increment_soft_daily=True,
            increment_paid_fallback_daily=False,
        )

    return AccessDecision(
        allowed=False,
        deny_message='Нажмите «Познакомиться с OpenClaw» для триала или «Тарифы и оплата» для подписки.',
        provider_name=settings.fallback_provider,
        increment_primary_daily=False,
        increment_trial=False,
        increment_soft_daily=False,
        increment_paid_fallback_daily=False,
    )


async def maybe_send_token_warnings(
    *,
    redis: Redis,
    user: User,
    settings: Settings,
    used_before: int,
    used_after: int,
    send_message: Callable[[str], Awaitable[None]],
) -> None:
    if user.subscription_period_start is None:
        return
    limit = settings.paid_token_limit_for_plan(user.plan)
    if limit <= 0:
        return
    remaining_after = limit - used_after
    pct_remaining = remaining_after / limit
    period_tag = str(int(user.subscription_period_start.timestamp()))

    if remaining_after <= int(limit * 0.20) and (limit - used_before) > int(limit * 0.20):
        key = f"tokwarn:20:{user.id}:{period_tag}"
        if not await redis.get(key):
            await redis.set(key, "1", ex=90 * 86400)
            await send_message(
                f"⚠️ Осталось меньше 20% токенов на период: ~{max(0, remaining_after):,} из {limit:,}."
            )

    if remaining_after <= int(limit * 0.05) and (limit - used_before) > int(limit * 0.05):
        key = f"tokwarn:5:{user.id}:{period_tag}"
        if not await redis.get(key):
            await redis.set(key, "1", ex=90 * 86400)
            await send_message(
                f"🔻 Осталось меньше 5% токенов на период: ~{max(0, remaining_after):,} из {limit:,}. "
                "Далее включится экономичный режим (Ollama) с дневным лимитом."
            )
