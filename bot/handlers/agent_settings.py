"""Настройка персонализации агента (OpenClaw) в Telegram: имя, инструкции, сброс диалога."""

from __future__ import annotations

import html
import secrets

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.menu import main_menu_reply_keyboard
from core.config import get_settings
from core.database import SessionLocal
from models.user import User
from services.app_config import is_internal_access_allowed
from services.metrics_service import record_event
from services.user_service import UserService

router = Router()

_MAX_NAME = 128
_MAX_INSTR = 8000


class AgentSettingsStates(StatesGroup):
    waiting_name = State()
    waiting_instructions = State()


class AgentSettingsButtonFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return (message.text or "").strip() == get_settings().btn_agent_settings


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Имя ассистента", callback_data="ags:name")],
            [InlineKeyboardButton(text="📋 Инструкции (роль, стиль)", callback_data="ags:instr")],
            [
                InlineKeyboardButton(text="🗑 Сбросить имя", callback_data="ags:clr_name"),
                InlineKeyboardButton(text="🗑 Сбросить инструкции", callback_data="ags:clr_instr"),
            ],
            [InlineKeyboardButton(text="🔄 Новый диалог (сессия OpenClaw)", callback_data="ags:reset_session")],
            [InlineKeyboardButton(text="« Закрыть", callback_data="ags:close")],
        ]
    )


async def _ensure_access(message: Message) -> bool:
    settings = get_settings()
    async with SessionLocal() as session:
        ok = await is_internal_access_allowed(message.from_user.id, settings, session)
    if not ok:
        await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
    return ok


def _format_menu_text(user: User) -> str:
    name = (user.agent_display_name or "").strip() or "—"
    instr = (user.agent_instructions or "").strip()
    if instr:
        preview = instr if len(instr) <= 400 else instr[:397] + "…"
        instr_block = html.escape(preview)
    else:
        instr_block = "—"
    sess = (user.openclaw_session_id or "").strip() or f"telegram-{user.id} (по умолчанию)"
    return (
        "<b>Настройки ассистента</b> (для ответов через <b>OpenClaw</b>)\n\n"
        f"Имя / как представляться: <b>{html.escape(name)}</b>\n\n"
        f"Инструкции:\n<pre>{instr_block}</pre>\n\n"
        f"<i>Сессия OpenClaw:</i> <code>{html.escape(sess[:200])}</code>\n"
        "«Новый диалог» создаёт новый ключ сессии — история в Gateway начнётся с нуля."
    )


async def _open_menu(message: Message, state: FSMContext, *, answer_target: Message | None = None) -> None:
    await state.clear()
    if not await _ensure_access(message):
        return
    tgt = answer_target or message
    async with SessionLocal() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            await tgt.answer("Сначала отправьте /start.")
            return
        text = _format_menu_text(user)
    await tgt.answer(text, reply_markup=_menu_kb())


@router.message(Command("agent"))
async def cmd_agent(message: Message, state: FSMContext) -> None:
    await _open_menu(message, state)


@router.message(AgentSettingsButtonFilter())
async def btn_agent_settings(message: Message, state: FSMContext) -> None:
    await _open_menu(message, state)


@router.callback_query(F.data == "ags:close")
async def ags_close(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "ags:name")
async def ags_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    uid = callback.from_user.id
    settings = get_settings()
    async with SessionLocal() as session:
        if not await is_internal_access_allowed(uid, settings, session):
            await callback.answer("Нет доступа.", show_alert=True)
            return
    await state.set_state(AgentSettingsStates.waiting_name)
    if callback.message:
        await callback.message.edit_text(
            "Введите <b>имя или короткую роль</b> ассистента одним сообщением "
            f"(до {_MAX_NAME} символов). /cancel — отмена.",
        )
    await callback.answer()


@router.callback_query(F.data == "ags:instr")
async def ags_instr_start(callback: CallbackQuery, state: FSMContext) -> None:
    uid = callback.from_user.id
    settings = get_settings()
    async with SessionLocal() as session:
        if not await is_internal_access_allowed(uid, settings, session):
            await callback.answer("Нет доступа.", show_alert=True)
            return
    await state.set_state(AgentSettingsStates.waiting_instructions)
    if callback.message:
        await callback.message.edit_text(
            "Отправьте <b>инструкции</b> для ассистента (стиль, ограничения, задачи). "
            f"До {_MAX_INSTR} символов; лишнее обрежется. /cancel — отмена.",
        )
    await callback.answer()


@router.callback_query(F.data == "ags:clr_name")
async def ags_clr_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    uid = callback.from_user.id
    settings = get_settings()
    async with SessionLocal() as session:
        if not await is_internal_access_allowed(uid, settings, session):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        user = await session.get(User, uid)
        if user:
            user.agent_display_name = None
            await session.commit()
    await record_event("agent_settings_clear_name", user_id=uid)
    await callback.answer("Имя сброшено")
    if callback.message:
        await _open_menu_from_callback(callback)


@router.callback_query(F.data == "ags:clr_instr")
async def ags_clr_instr(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    uid = callback.from_user.id
    settings = get_settings()
    async with SessionLocal() as session:
        if not await is_internal_access_allowed(uid, settings, session):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        user = await session.get(User, uid)
        if user:
            user.agent_instructions = None
            await session.commit()
    await record_event("agent_settings_clear_instructions", user_id=uid)
    await callback.answer("Инструкции сброшены")
    if callback.message:
        await _open_menu_from_callback(callback)


@router.callback_query(F.data == "ags:reset_session")
async def ags_reset_session(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    uid = callback.from_user.id
    settings = get_settings()
    new_key = f"telegram-{uid}-{secrets.token_hex(4)}"
    async with SessionLocal() as session:
        if not await is_internal_access_allowed(uid, settings, session):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        user = await session.get(User, uid)
        if user:
            user.openclaw_session_id = new_key
            await session.commit()
    await record_event("agent_settings_reset_session", user_id=uid, payload={"session": new_key})
    await callback.answer("Новая сессия OpenClaw")
    if callback.message:
        await _open_menu_from_callback(callback)


async def _open_menu_from_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    msg = callback.message
    uid = callback.from_user.id
    async with SessionLocal() as session:
        user = await session.get(User, uid)
        if not user:
            await msg.edit_text("Пользователь не найден. /start")
            return
        text = _format_menu_text(user)
    await msg.edit_text(text, reply_markup=_menu_kb())


@router.message(
    StateFilter(AgentSettingsStates.waiting_name, AgentSettingsStates.waiting_instructions),
    Command("cancel"),
)
async def agent_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_reply_keyboard())


@router.message(StateFilter(AgentSettingsStates.waiting_name), F.text)
async def agent_save_name(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение — введите текст или /cancel")
        return
    name = raw[:_MAX_NAME]
    async with SessionLocal() as session:
        user_service = UserService(session)
        user, _ = await user_service.get_or_create(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        user.agent_display_name = name
        await session.commit()
    await state.clear()
    await record_event("agent_settings_name", user_id=message.from_user.id)
    await message.answer(
        f"Сохранено: <b>{html.escape(name)}</b>\n\nДальше ответы через OpenClaw будут с этой персонализацией.",
        reply_markup=main_menu_reply_keyboard(),
    )


@router.message(StateFilter(AgentSettingsStates.waiting_instructions), F.text)
async def agent_save_instructions(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение — введите текст или /cancel")
        return
    instr = raw[:_MAX_INSTR]
    async with SessionLocal() as session:
        user_service = UserService(session)
        user, _ = await user_service.get_or_create(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        user.agent_instructions = instr
        await session.commit()
    await state.clear()
    await record_event("agent_settings_instructions", user_id=message.from_user.id)
    await message.answer(
        "Инструкции сохранены. Они добавляются к каждому запросу в OpenClaw.",
        reply_markup=main_menu_reply_keyboard(),
    )


# Не-текст в состоянии ожидания
@router.message(StateFilter(AgentSettingsStates.waiting_name, AgentSettingsStates.waiting_instructions))
async def agent_waiting_non_text(message: Message, state: FSMContext) -> None:
    await message.answer("Нужно текстовое сообщение или /cancel")
