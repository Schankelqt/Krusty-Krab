"""Пошаговая выдача подписки админу: один раз вводит Telegram id, дальше — кнопки."""

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.config import get_settings
from core.database import SessionLocal
from services.metrics_service import record_event
from services.subscription_service import activate_paid_subscription
from services.user_service import UserService

router = Router()

_VALID_PLANS = ("basic", "standard", "pro")


class AdminGrantWizard(StatesGroup):
    waiting_user_id = State()
    choosing_plan = State()
    choosing_line = State()


def _admin_ok(uid: int) -> bool:
    return uid in get_settings().admin_id_set


def _plan_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Basic", callback_data="agw:p:basic"),
                InlineKeyboardButton(text="Standard", callback_data="agw:p:standard"),
                InlineKeyboardButton(text="Pro", callback_data="agw:p:pro"),
            ],
            [InlineKeyboardButton(text="« Отмена", callback_data="agw:cancel")],
        ]
    )


def _line_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="GPT", callback_data="agw:l:gpt"),
                InlineKeyboardButton(text="Claude", callback_data="agw:l:claude"),
                InlineKeyboardButton(text="Gemini", callback_data="agw:l:gemini"),
            ],
            [
                InlineKeyboardButton(text="Линию не менять", callback_data="agw:l:keep"),
                InlineKeyboardButton(text="Сбросить линию", callback_data="agw:l:clear"),
            ],
            [InlineKeyboardButton(text="« Отмена", callback_data="agw:cancel")],
        ]
    )


@router.message(Command("admin_grant_ui"))
async def cmd_grant_ui(message: Message, state: FSMContext) -> None:
    if not _admin_ok(message.from_user.id):
        await message.answer("Команда только для администраторов.")
        return
    await state.set_state(AdminGrantWizard.waiting_user_id)
    await message.answer(
        "<b>Выдача подписки</b>\n"
        "Отправьте <b>одним сообщением</b> числовой Telegram user id целевого пользователя "
        "(он должен хотя бы раз написать боту <code>/start</code>).\n\n"
        "Отмена: кнопка ниже после шага с кнопками или снова <code>/admin_grant_ui</code>."
    )


@router.message(StateFilter(AdminGrantWizard.waiting_user_id), F.text)
async def grant_receive_user_id(message: Message, state: FSMContext) -> None:
    if not _admin_ok(message.from_user.id):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен только числовой id, без пробелов и текста. Попробуйте ещё раз.")
        return
    user_id = int(raw)
    async with SessionLocal() as session:
        user = await UserService(session).get(user_id)
    if not user:
        await message.answer("Пользователь не найден в базе. Пусть сначала отправит /start.")
        return
    await state.update_data(target_id=user_id)
    await state.set_state(AdminGrantWizard.choosing_plan)
    await message.answer(
        f"Пользователь <code>{user_id}</code> найден. Выберите план:",
        reply_markup=_plan_kb(),
    )


@router.callback_query(F.data == "agw:cancel")
async def grant_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Выдача подписки отменена.")
    await callback.answer()


@router.callback_query(StateFilter(AdminGrantWizard.choosing_plan), F.data.startswith("agw:p:"))
async def grant_pick_plan(callback: CallbackQuery, state: FSMContext) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    plan = (callback.data or "").split(":")[-1].lower()
    if plan not in _VALID_PLANS:
        await callback.answer("Неизвестный план", show_alert=True)
        return
    await state.update_data(plan=plan)
    await state.set_state(AdminGrantWizard.choosing_line)
    if callback.message:
        await callback.message.edit_text(
            f"План: <b>{plan}</b>.\nВыберите линию API (или оставьте как есть):",
            reply_markup=_line_kb(),
        )
    await callback.answer()


@router.callback_query(StateFilter(AdminGrantWizard.choosing_line), F.data.startswith("agw:l:"))
async def grant_pick_line(callback: CallbackQuery, state: FSMContext) -> None:
    if not _admin_ok(callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    target_id = data.get("target_id")
    plan = data.get("plan")
    if not isinstance(target_id, int) or not isinstance(plan, str):
        await state.clear()
        await callback.answer("Сессия устарела. Запустите /admin_grant_ui снова.", show_alert=True)
        return

    key = (callback.data or "").split(":")[-1].lower()
    line_kw: str | None = None
    line_clear = False
    if key == "keep":
        pass
    elif key == "clear":
        line_clear = True
    elif key in {"gpt", "claude", "gemini"}:
        line_kw = key
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    async with SessionLocal() as session:
        user = await UserService(session).get(target_id)
        if not user:
            await state.clear()
            if callback.message:
                await callback.message.edit_text("Пользователь не найден. Запустите мастер заново.")
            await callback.answer()
            return
        await activate_paid_subscription(
            session,
            target_id,
            plan=plan,
            billing_llm_line=line_kw,
            billing_llm_line_clear=line_clear,
        )
        await session.commit()

    await state.clear()
    await record_event(
        "admin_grant",
        user_id=target_id,
        payload={
            "by_admin": callback.from_user.id,
            "plan": plan,
            "llm_line": line_kw,
            "line_cleared": line_clear,
            "via": "admin_grant_ui",
        },
    )

    extra: list[str] = [f"план <b>{plan}</b>"]
    if line_clear:
        extra.append("линия <b>сброшена</b>")
    elif line_kw:
        extra.append(f"линия <b>{line_kw}</b>")
    suffix = f" ({', '.join(extra)})"
    if callback.message:
        await callback.message.edit_text(f"Пользователь <code>{target_id}</code> активирован.{suffix}")
    await callback.answer("Готово")
