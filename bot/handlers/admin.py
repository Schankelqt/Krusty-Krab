from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.config import get_settings
from core.database import SessionLocal
from services.metrics_reporter import send_daily_report
from services.metrics_service import record_event
from services.subscription_service import activate_paid_subscription, revoke_paid_subscription
from services.user_service import UserService

router = Router()

_VALID_PLANS = frozenset({"basic", "standard", "pro"})
_VALID_LINES = frozenset({"gpt", "claude", "gemini"})
_LINE_CLEAR = frozenset({"-", "none", "clear"})


@router.message(Command("admin_grant"))
async def admin_grant(message: Message) -> None:
    settings = get_settings()
    actor_id = message.from_user.id
    if actor_id not in settings.admin_id_set:
        await message.answer("Нет доступа к admin-командам.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Формат:\n"
            "<code>/admin_grant &lt;telegram_user_id&gt;</code>\n"
            "<code>/admin_grant &lt;id&gt; basic|standard|pro</code>\n"
            "<code>/admin_grant &lt;id&gt; basic|standard|pro gpt|claude|gemini</code>\n"
            "Четвёртым аргументом можно <code>-</code> / <code>none</code> / <code>clear</code> — сбросить линию API.\n\n"
            "Удобнее: <code>/admin_grant_ui</code> или кнопка в <code>/admin</code> — id один раз, дальше кнопки.",
        )
        return
    if len(parts) > 4:
        await message.answer("Слишком много аргументов.")
        return

    user_id = int(parts[1])
    plan_kw: str | None = None
    line_kw: str | None = None
    line_clear = False
    if len(parts) >= 3:
        plan_kw = parts[2].strip().lower()
        if plan_kw not in _VALID_PLANS:
            await message.answer("Неверный план. Доступно: basic, standard, pro.")
            return
    if len(parts) == 4:
        raw_line = parts[3].strip().lower()
        if raw_line in _LINE_CLEAR:
            line_clear = True
        elif raw_line in _VALID_LINES:
            line_kw = raw_line
        else:
            await message.answer(
                "Неверная линия. Доступно: gpt, claude, gemini или сброс: -, none, clear.",
            )
            return

    async with SessionLocal() as session:
        user_service = UserService(session)
        user = await user_service.get(user_id)
        if not user:
            await message.answer("Пользователь не найден в базе. Пусть сначала отправит /start.")
            return
        await activate_paid_subscription(
            session,
            user_id,
            plan=plan_kw,
            billing_llm_line=line_kw,
            billing_llm_line_clear=line_clear,
        )
        await session.commit()

    await record_event(
        "admin_grant",
        user_id=user_id,
        payload={
            "by_admin": actor_id,
            "plan": plan_kw,
            "llm_line": line_kw,
            "line_cleared": line_clear,
        },
    )
    extra = []
    if plan_kw:
        extra.append(f"план <b>{plan_kw}</b>")
    if line_clear:
        extra.append("линия <b>сброшена</b>")
    elif line_kw:
        extra.append(f"линия <b>{line_kw}</b>")
    suffix = f" ({', '.join(extra)})" if extra else ""
    await message.answer(f"Пользователь {user_id} активирован.{suffix}")


@router.message(Command("admin_revoke"))
async def admin_revoke(message: Message) -> None:
    settings = get_settings()
    if message.from_user.id not in settings.admin_id_set:
        await message.answer("Нет доступа к admin-командам.")
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/admin_revoke &lt;telegram_user_id&gt;</code>")
        return

    user_id = int(parts[1])
    async with SessionLocal() as session:
        user_service = UserService(session)
        user = await user_service.get(user_id)
        if not user:
            await message.answer("Пользователь не найден в базе.")
            return
        await revoke_paid_subscription(session, user_id)
        await session.commit()

    await record_event("admin_revoke", user_id=user_id, payload={"by_admin": message.from_user.id})
    await message.answer(
        f"Пользователь {user_id}: подписка снята (период очищен, план basic, линия API сброшена). "
        "Триал не трогаем — если уже был использован, остаётся soft/оплата.",
    )


@router.message(Command("report_now"))
async def report_now(message: Message) -> None:
    settings = get_settings()
    if message.from_user.id not in settings.admin_id_set:
        await message.answer("Нет доступа к admin-командам.")
        return
    if not settings.metrics_report_chat_id.strip():
        await message.answer("Задайте <code>METRICS_REPORT_CHAT_ID</code> (id канала/чата для отчётов).")
        return
    try:
        await send_daily_report(message.bot, settings)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Не удалось отправить отчёт: {exc}")
        return
    await record_event("report_now_sent", user_id=message.from_user.id)
    await message.answer("Отчёт отправлен в канал/чат из <code>METRICS_REPORT_CHAT_ID</code>.")
