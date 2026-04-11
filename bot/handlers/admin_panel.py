"""Интерактивная панель настроек для админов (БД app_settings)."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.admin_grant_wizard import AdminGrantWizard

from core.config import get_settings
from core.database import SessionLocal
from services.app_config import (
    K_NOTIFY_ERRORS,
    K_NOTIFY_NEW_USER,
    K_NOTIFY_PAYMENT,
    K_PAID_FB,
    K_SOFT_DAILY,
    K_SUB_REMIND_DAYS,
    K_TRIAL_HOURS,
    K_TRIAL_MSG,
    K_WHITELIST_EXTRA,
    get_whitelist_extra_ids,
    invalidate_app_config_cache,
    load_notify_config,
    load_product_limits,
    upsert_setting,
)
from sqlalchemy import func, select

from models.app_setting import AppSetting
from models.user import User

router = Router()


def _admin_ok(uid: int) -> bool:
    return uid in get_settings().admin_id_set


def _main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Сводка", callback_data="adm:summary")],
            [InlineKeyboardButton(text="🎁 Выдать подписку (кнопки)", callback_data="adm:grant_ui")],
            [InlineKeyboardButton(text="⚙️ Лимиты продукта", callback_data="adm:limits")],
            [InlineKeyboardButton(text="🔔 Уведомления", callback_data="adm:notif")],
            [InlineKeyboardButton(text="🛡 Whitelist (тест)", callback_data="adm:wl")],
            [InlineKeyboardButton(text="🔄 Сбросить кеш настроек", callback_data="adm:cache")],
        ]
    )


@router.message(Command("admin"))
async def cmd_admin_panel(message: Message) -> None:
    if not _admin_ok(message.from_user.id):
        await message.answer("Команда только для администраторов.")
        return
    await message.answer(
        "<b>Панель администратора</b>\n"
        "Настройки ниже хранятся в базе и перекрывают значения из .env до сброса.\n"
        "Команды <code>/admin_grant</code>, <code>/admin_revoke</code>, <code>/report_now</code> без изменений.\n"
        "Удобная выдача: <code>/admin_grant_ui</code> или кнопка ниже.",
        reply_markup=_main_kb(),
    )


@router.callback_query(F.data == "adm:grant_ui")
async def adm_grant_ui(callback: CallbackQuery, state: FSMContext) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminGrantWizard.waiting_user_id)
    text = (
        "<b>Выдача подписки</b>\n"
        "Отправьте <b>одним сообщением</b> числовой Telegram user id "
        "(целевой пользователь должен хотя бы раз написать боту <code>/start</code>).\n\n"
        "<code>/admin_grant_ui</code> — то же самое из чата."
    )
    if callback.message:
        await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data == "adm:home")
async def adm_home(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text(
            "<b>Панель администратора</b>",
            reply_markup=_main_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "adm:summary")
async def adm_summary(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    settings = get_settings()
    async with SessionLocal() as session:
        pl = await load_product_limits(session, settings)
        nc = await load_notify_config(session, settings)
        n_users = await session.scalar(select(func.count()).select_from(User))
        n_active = await session.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
        n_rows = await session.scalar(select(func.count()).select_from(AppSetting))

    text = (
        "<b>Сводка</b>\n"
        f"Пользователей в БД: <b>{n_users}</b>\n"
        f"С флагом is_active: <b>{n_active}</b>\n"
        f"Переопределений в app_settings: <b>{n_rows}</b>\n\n"
        "<b>Эффективные лимиты</b>\n"
        f"• Триал: {pl.trial_duration_hours} ч / {pl.trial_message_limit} сообщ.\n"
        f"• Soft в день: {pl.soft_daily_message_limit}\n"
        f"• Paid fallback в день: {pl.paid_fallback_daily_message_limit}\n\n"
        "<b>Уведомления</b>\n"
        f"• Напоминание клиенту за {nc.subscription_reminder_days} дн. до конца периода (0 = выкл)\n"
        f"• Алерты команде: новый пользователь {'✓' if nc.notify_admins_new_user else '✗'}, "
        f"оплата {'✓' if nc.notify_admins_payment else '✗'}, "
        f"ошибки {'✓' if nc.notify_admins_errors else '✗'}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад", callback_data="adm:home")],
        ]
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


async def _render_limits(callback: CallbackQuery) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        pl = await load_product_limits(session, settings)
    text = (
        "<b>Лимиты</b> (нажмите пресет; значения сразу в БД)\n\n"
        f"Сейчас: триал <b>{pl.trial_duration_hours}</b> ч, <b>{pl.trial_message_limit}</b> сообщ.; "
        f"soft/день <b>{pl.soft_daily_message_limit}</b>; paid fallback/день <b>{pl.paid_fallback_daily_message_limit}</b>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Триал 24ч", callback_data="adm:lh:24"),
                InlineKeyboardButton(text="48ч", callback_data="adm:lh:48"),
                InlineKeyboardButton(text="72ч", callback_data="adm:lh:72"),
            ],
            [
                InlineKeyboardButton(text="Сообщ. триала 30", callback_data="adm:lm:30"),
                InlineKeyboardButton(text="50", callback_data="adm:lm:50"),
                InlineKeyboardButton(text="100", callback_data="adm:lm:100"),
            ],
            [
                InlineKeyboardButton(text="Soft 2/д", callback_data="adm:ls:2"),
                InlineKeyboardButton(text="3", callback_data="adm:ls:3"),
                InlineKeyboardButton(text="5", callback_data="adm:ls:5"),
            ],
            [
                InlineKeyboardButton(text="Fallback 100/д", callback_data="adm:lf:100"),
                InlineKeyboardButton(text="300", callback_data="adm:lf:300"),
                InlineKeyboardButton(text="500", callback_data="adm:lf:500"),
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="adm:home")],
        ]
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm:limits")
async def adm_limits(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await _render_limits(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:lh:"))
async def adm_set_trial_h(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    h = int((callback.data or "").split(":")[-1])
    async with SessionLocal() as session:
        await upsert_setting(session, K_TRIAL_HOURS, {"v": h})
    await callback.answer(f"Триал: {h} ч")
    await _render_limits(callback)


@router.callback_query(F.data.startswith("adm:lm:"))
async def adm_set_trial_m(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    m = int((callback.data or "").split(":")[-1])
    async with SessionLocal() as session:
        await upsert_setting(session, K_TRIAL_MSG, {"v": m})
    await callback.answer(f"Лимит сообщений триала: {m}")
    await _render_limits(callback)


@router.callback_query(F.data.startswith("adm:ls:"))
async def adm_set_soft(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    m = int((callback.data or "").split(":")[-1])
    async with SessionLocal() as session:
        await upsert_setting(session, K_SOFT_DAILY, {"v": m})
    await callback.answer(f"Soft: {m}/день")
    await _render_limits(callback)


@router.callback_query(F.data.startswith("adm:lf:"))
async def adm_set_fb(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    m = int((callback.data or "").split(":")[-1])
    async with SessionLocal() as session:
        await upsert_setting(session, K_PAID_FB, {"v": m})
    await callback.answer(f"Paid fallback: {m}/день")
    await _render_limits(callback)


async def _render_notif(callback: CallbackQuery) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        nc = await load_notify_config(session, settings)
    text = (
        "<b>Уведомления</b>\n"
        f"Новый пользователь: {'вкл' if nc.notify_admins_new_user else 'выкл'}\n"
        f"Успешная оплата: {'вкл' if nc.notify_admins_payment else 'выкл'}\n"
        f"Ошибки бота: {'вкл' if nc.notify_admins_errors else 'выкл'}\n"
        f"Напоминание клиенту до конца подписки: <b>{nc.subscription_reminder_days}</b> дн. (0 = выкл)"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✓' if nc.notify_admins_new_user else '○'} Новый user",
                    callback_data="adm:tnu",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✓' if nc.notify_admins_payment else '○'} Оплата",
                    callback_data="adm:tpm",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✓' if nc.notify_admins_errors else '○'} Ошибки",
                    callback_data="adm:ter",
                )
            ],
            [
                InlineKeyboardButton(text="Напоминание: выкл", callback_data="adm:rd:0"),
                InlineKeyboardButton(text="3д", callback_data="adm:rd:3"),
                InlineKeyboardButton(text="7д", callback_data="adm:rd:7"),
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="adm:home")],
        ]
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm:notif")
async def adm_notif(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await _render_notif(callback)
    await callback.answer()


async def _toggle_notify(session, key: str) -> None:
    row = await session.get(AppSetting, key)
    cur = True
    if row is not None:
        cur = bool(row.value.get("enabled", True))
    await upsert_setting(session, key, {"enabled": not cur})


@router.callback_query(F.data == "adm:tnu")
async def adm_tnu(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    async with SessionLocal() as session:
        await _toggle_notify(session, K_NOTIFY_NEW_USER)
    await callback.answer("Обновлено")
    await _render_notif(callback)


@router.callback_query(F.data == "adm:tpm")
async def adm_tpm(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    async with SessionLocal() as session:
        await _toggle_notify(session, K_NOTIFY_PAYMENT)
    await callback.answer("Обновлено")
    await _render_notif(callback)


@router.callback_query(F.data == "adm:ter")
async def adm_ter(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    async with SessionLocal() as session:
        await _toggle_notify(session, K_NOTIFY_ERRORS)
    await callback.answer("Обновлено")
    await _render_notif(callback)


@router.callback_query(F.data.startswith("adm:rd:"))
async def adm_rd(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    d = int((callback.data or "").split(":")[-1])
    async with SessionLocal() as session:
        await upsert_setting(session, K_SUB_REMIND_DAYS, {"v": d})
    await callback.answer(f"Напоминание: {d} дн.")
    await _render_notif(callback)


@router.callback_query(F.data == "adm:cache")
async def adm_cache(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    invalidate_app_config_cache()
    await callback.answer("Кеш сброшен", show_alert=True)


@router.callback_query(F.data == "adm:wl")
async def adm_wl(callback: CallbackQuery) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    async with SessionLocal() as session:
        ids = sorted(await get_whitelist_extra_ids(session))
    text = (
        "<b>Доп. whitelist</b> (только при INTERNAL_TEST_MODE)\n"
        f"Telegram id: <code>{', '.join(str(i) for i in ids) or '—'}</code>\n\n"
        "Добавьте id через:\n"
        "<code>/whitelist_add 123456789</code>\n"
        "<code>/whitelist_remove 123456789</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="adm:home")]]
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.message(Command("whitelist_add"))
async def whitelist_add_cmd(message: Message) -> None:
    if not _admin_ok(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/whitelist_add &lt;telegram_user_id&gt;</code>")
        return
    uid = int(parts[1])
    async with SessionLocal() as session:
        ids = sorted(await get_whitelist_extra_ids(session))
        if uid not in ids:
            ids.append(uid)
        await upsert_setting(session, K_WHITELIST_EXTRA, {"ids": ids})
    await message.answer(f"ID <code>{uid}</code> добавлен в доп. whitelist.")


@router.message(Command("whitelist_remove"))
async def whitelist_remove_cmd(message: Message) -> None:
    if not _admin_ok(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/whitelist_remove &lt;telegram_user_id&gt;</code>")
        return
    uid = int(parts[1])
    async with SessionLocal() as session:
        ids = [i for i in await get_whitelist_extra_ids(session) if i != uid]
        await upsert_setting(session, K_WHITELIST_EXTRA, {"ids": sorted(ids)})
    await message.answer(f"ID <code>{uid}</code> убран из доп. whitelist (если был).")

