from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from redis.asyncio import from_url as redis_from_url

from bot.keyboards.plans import plans_inline_keyboard
from core.config import get_settings
from core.database import SessionLocal
from services.access_policy import (
    maybe_send_token_warnings,
    paid_period_active,
    paid_period_boundaries_missing,
    resolve_chat_access,
    trial_active,
)
from services.app_config import is_internal_access_allowed, load_product_limits
from services.checkout_service import create_subscription_checkout_url
from services.limits_service import LimitsService
from services.llm_router import LLMRouter
from services.metrics_service import record_event
from services.usage_service import UsageService
from services.subscription_service import activate_paid_subscription
from services.user_service import UserService

router = Router()


def _trial_provider_label(settings) -> str:
    p = settings.trial_provider
    return {"ollama": "Ollama", "mock": "mock"}.get(p, p)


@router.message(Command("tokens"))
async def show_tokens(message: Message) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        if not await is_internal_access_allowed(message.from_user.id, settings, session):
            await record_event("whitelist_blocked", user_id=message.from_user.id, payload={"where": "command_tokens"})
            await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
            return

        user_service = UserService(session)
        usage_service = UsageService(session)
        pl = await load_product_limits(session, settings)
        user, _ = await user_service.get_or_create(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        now = datetime.now(timezone.utc)

        if user.subscription_period_start is None or user.subscription_period_end is None:
            lines: list[str] = []
            if trial_active(user, pl, now):
                assert user.trial_started_at is not None
                end = user.trial_started_at
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                trial_end = end + timedelta(hours=pl.trial_duration_hours)
                lines.append("Триал активен.")
                lines.append(f"Сообщений триала: {user.trial_message_count}/{pl.trial_message_limit}")
                lines.append(f"До конца триала (UTC): {trial_end:%d.%m.%Y %H:%M}")
            elif user.trial_started_at is not None:
                lines.append("Триал завершён. Доступен мягкий режим или подписка.")
            else:
                lines.append("Платный период не начат — нажмите триал или оплату.")
            await message.answer("\n".join(lines))
            await record_event(
                "command_tokens",
                user_id=message.from_user.id,
                payload={"segment": "no_paid_period"},
            )
            return

        start = user.subscription_period_start
        end = user.subscription_period_end
        used = await usage_service.get_metered_tokens_in_period(
            user.id, start, end, providers=settings.metering_primary_providers
        )
        token_limit = settings.paid_token_limit_for_plan(user.plan)
        remaining = max(0, token_limit - used)
        expired = now >= end
        last_inclusive = end - timedelta(seconds=1)

        lines = [
            f"Период (UTC): с {start:%d.%m.%Y %H:%M} по {last_inclusive:%d.%m.%Y %H:%M} включительно.",
        ]
        if expired:
            lines.append("Текущий оплаченный период завершён — для нового лимита продлите подписку.")
        line_label = (user.billing_llm_line or "—").upper()
        lines.extend(
            [
                f"Линия API: {line_label} (пусто = глобальный PRIMARY_PROVIDER, напр. OpenClaw).",
                f"Использовано токенов (только платные API, без Ollama/mock): {used:,}",
                f"Лимит за период (пакет {user.plan}): {token_limit:,}",
                f"Остаток: {remaining:,}",
            ]
        )
        await message.answer("\n".join(lines))
        await record_event(
            "command_tokens",
            user_id=message.from_user.id,
            payload={
                "segment": "paid_period",
                "plan": user.plan,
                "billing_llm_line": user.billing_llm_line,
                "expired": expired,
            },
        )


@router.callback_query(F.data.startswith("pay:"))
async def on_plan_checkout(callback: CallbackQuery) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        if not await is_internal_access_allowed(callback.from_user.id, settings, session):
            await record_event("whitelist_blocked", user_id=callback.from_user.id, payload={"where": "pay_callback"})
            await callback.answer("Нет доступа.", show_alert=True)
            return

    if not settings.yukassa_configured:
        await callback.answer("Оплата не настроена.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[0] != "pay":
        await callback.answer()
        return
    _, llm_line, plan = parts
    llm_line = llm_line.strip().lower()
    plan = plan.strip().lower()
    if llm_line not in ("gpt", "claude", "gemini") or plan not in ("basic", "standard", "pro"):
        await callback.answer()
        return

    async with SessionLocal() as session:
        user_service = UserService(session)
        await user_service.get_or_create(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        try:
            url = await create_subscription_checkout_url(
                session,
                settings,
                user_id=callback.from_user.id,
                plan=plan,
                llm_line=llm_line,
            )
        except Exception as exc:  # noqa: BLE001
            await record_event(
                "checkout_failed",
                user_id=callback.from_user.id,
                payload={"plan": plan, "llm_line": llm_line, "error": str(exc)[:500]},
            )
            await callback.answer(f"Ошибка: {exc}", show_alert=True)
            return

    await record_event(
        "checkout_created",
        user_id=callback.from_user.id,
        payload={"plan": plan, "llm_line": llm_line},
    )
    amount = settings.billing_amount_rub(llm_line, plan)
    text = (
        f"<b>{llm_line.upper()}</b>, пакет <b>{plan}</b> — "
        f"оплата {amount} {settings.yukassa_currency}:\n{url}"
    )
    if callback.message:
        await callback.message.answer(text)
    await callback.answer()


@router.message(F.text)
async def handle_text(message: Message) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    settings = get_settings()
    async with SessionLocal() as session:
        allowed = await is_internal_access_allowed(message.from_user.id, settings, session)
    if not allowed:
        await record_event("whitelist_blocked", user_id=message.from_user.id, payload={"where": "text_message"})
        await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
        return

    if text.startswith("/"):
        return

    if text == settings.btn_plans:
        if not settings.yukassa_configured:
            await record_event("plans_button_no_yookassa", user_id=message.from_user.id)
            await message.answer(
                "Оплата через ЮKassa пока не настроена (нет ключей в .env). "
                "Доступны триал и мягкий режим; для теста подписки администратор может выдать доступ командой /admin_grant."
            )
            return
        await record_event("plans_keyboard_shown", user_id=message.from_user.id)
        await message.answer(
            "Выберите линию модели и пакет токенов на период (1M / 2M / 3M):",
            reply_markup=plans_inline_keyboard(),
        )
        return

    if text == settings.btn_trial:
        await _handle_trial_button(message)
        return

    await _handle_llm_message(message, text)


async def _handle_trial_button(message: Message) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        user_service = UserService(session)
        pl = await load_product_limits(session, settings)
        user, _ = await user_service.get_or_create(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        if user.is_active:
            if paid_period_active(user, now):
                await record_event("trial_button_already_paid_active", user_id=message.from_user.id)
                await message.answer("У вас уже активна оплаченная подписка в текущем периоде.")
            elif paid_period_boundaries_missing(user):
                await activate_paid_subscription(session, user.id)
                await session.commit()
                await record_event("trial_button_repaired_missing_period", user_id=message.from_user.id)
                await message.answer(
                    "Обновили биллинговый период под вашу подписку. Можете пользоваться ассистентом обычными сообщениями в чат."
                )
            else:
                await record_event("trial_button_paid_period_inactive", user_id=message.from_user.id)
                await message.answer(
                    "Платный период сейчас не в активном окне (например, срок по датам истёк). "
                    "Продлите подписку в «Тарифы и оплата» или воспользуйтесь мягким режимом в пределах дневного лимита."
                )
            return
        if trial_active(user, pl, now):
            await record_event("trial_button_already_in_trial", user_id=message.from_user.id)
            await message.answer(
                f"Триал уже идёт: использовано {user.trial_message_count}/{pl.trial_message_limit} сообщений."
            )
            return
        if user.trial_started_at is not None:
            await record_event("trial_button_trial_used", user_id=message.from_user.id)
            await message.answer(
                "Триал уже использован. Доступен мягкий режим (несколько ответов в день) "
                "или подписка через «Тарифы и оплата»."
            )
            return
        user.trial_started_at = now
        user.trial_message_count = 0
        await session.commit()

    await record_event("trial_started", user_id=message.from_user.id)
    await message.answer(
        f"Триал запущен: {pl.trial_duration_hours} ч, до {pl.trial_message_limit} сообщений "
        f"через {_trial_provider_label(settings)}. Пишите обычным текстом в этот чат."
    )


async def _handle_llm_message(message: Message, text: str) -> None:
    settings = get_settings()
    redis_client = redis_from_url(settings.redis_url, decode_responses=True)
    now = datetime.now(timezone.utc)

    try:
        async with SessionLocal() as session:
            user_service = UserService(session)
            usage_service = UsageService(session)
            pl = await load_product_limits(session, settings)
            limits = LimitsService(redis_client, pl)
            user, _ = await user_service.get_or_create(
                user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )

            decision = await resolve_chat_access(
                user=user,
                settings=settings,
                product_limits=pl,
                now=now,
                usage_service=usage_service,
                limits=limits,
            )
            if not decision.allowed:
                await record_event(
                    "access_denied",
                    user_id=message.from_user.id,
                    payload={"reason": decision.deny_reason or "unknown"},
                )
                await message.answer(decision.deny_message or "Доступ временно недоступен.")
                return

            used_before = 0
            if paid_period_active(user, now):
                assert user.subscription_period_start is not None and user.subscription_period_end is not None
                used_before = await usage_service.get_metered_tokens_in_period(
                    user.id,
                    user.subscription_period_start,
                    user.subscription_period_end,
                    providers=settings.metering_primary_providers,
                )

            router_service = LLMRouter(redis_client=redis_client, db_session=session, product_limits=pl)
            try:
                response = await router_service.generate(
                    user=user,
                    prompt=text,
                    provider_name=decision.provider_name,
                    increment_primary_daily=decision.increment_primary_daily,
                )
            except Exception as exc:  # noqa: BLE001
                await record_event(
                    "llm_error",
                    user_id=message.from_user.id,
                    payload={
                        "provider": decision.provider_name,
                        "error": str(exc)[:500],
                    },
                )
                await message.answer(f"Ошибка LLM: {exc}")
                return

            if decision.increment_trial:
                user.trial_message_count += 1
            if decision.provider_name == "openclaw" and not user.openclaw_session_id:
                user.openclaw_session_id = f"telegram-{user.id}"

            await usage_service.log(user_id=user.id, prompt=text, response=response)

            if decision.increment_soft_daily:
                await limits.increment_soft_daily(user.id)
                await record_event("limit_soft_consumed", user_id=user.id)
            if decision.increment_paid_fallback_daily:
                await limits.increment_paid_fallback_daily(user.id)
                await record_event("limit_paid_fallback_consumed", user_id=user.id)

            reply_body = response.text
            if settings.show_llm_debug_in_reply:
                reply_body += f"\n\n(provider={response.provider}, model={response.model})"
            await message.answer(reply_body)

            await record_event(
                "llm_reply_success",
                user_id=user.id,
                payload={
                    "provider": response.provider,
                    "model": response.model,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out,
                    "user_plan": user.plan,
                    "billing_llm_line": user.billing_llm_line,
                    "increment_trial": decision.increment_trial,
                    "increment_soft_daily": decision.increment_soft_daily,
                    "increment_paid_fallback_daily": decision.increment_paid_fallback_daily,
                    "paid_period": paid_period_active(user, now),
                },
            )
            if decision.increment_trial:
                await record_event("trial_message_consumed", user_id=user.id)

            if paid_period_active(user, now):
                assert user.subscription_period_start is not None and user.subscription_period_end is not None
                used_after = await usage_service.get_metered_tokens_in_period(
                    user.id,
                    user.subscription_period_start,
                    user.subscription_period_end,
                    providers=settings.metering_primary_providers,
                )

                async def _notify(msg: str) -> None:
                    await message.answer(msg)

                for w in await maybe_send_token_warnings(
                    redis=redis_client,
                    user=user,
                    settings=settings,
                    used_before=used_before,
                    used_after=used_after,
                    send_message=_notify,
                ):
                    await record_event(w, user_id=user.id, payload={"used_after": used_after})
    finally:
        await redis_client.aclose()
