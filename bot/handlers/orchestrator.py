from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import text

from bot.keyboards.menu import main_menu_reply_keyboard
from core.config import get_settings
from core.database import SessionLocal
from services.app_config import is_internal_access_allowed
from services.metrics_service import record_event
from services import provisioning_service

router = Router()

_TEMPLATES: dict[str, str] = {
    "content": "Контент",
    "sales": "Продажи",
    "support": "Поддержка",
    "custom": "Кастом",
}


class OrchestratorStates(StatesGroup):
    waiting_goal = State()
    waiting_confirm = State()


def _template_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🧩 {title}", callback_data=f"orc:tpl:{key}")]
            for key, title in _TEMPLATES.items()
        ]
        + [[InlineKeyboardButton(text="Отмена", callback_data="orc:cancel")]]
    )


def _goal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="orc:goal_skip")],
            [InlineKeyboardButton(text="Отмена", callback_data="orc:cancel")],
        ]
    )


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="orc:confirm")],
            [InlineKeyboardButton(text="Отмена", callback_data="orc:cancel")],
        ]
    )


async def _check_internal_access(user_id: int) -> bool:
    settings = get_settings()
    async with SessionLocal() as session:
        return await is_internal_access_allowed(user_id, settings, session)


@router.message(Command("create_assistant"))
async def cmd_create_assistant(message: Message, state: FSMContext) -> None:
    if not await _check_internal_access(message.from_user.id):
        await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
        return

    await state.clear()
    await message.answer(
        "Создадим нового ассистента.\n\nШаг 1/2: выберите шаблон.",
        reply_markup=_template_kb(),
    )


@router.callback_query(F.data.startswith("orc:tpl:"))
async def orc_choose_template(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_internal_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    template_key = (callback.data or "").split(":")[-1]
    if template_key not in _TEMPLATES:
        await callback.answer()
        return

    await state.update_data(template_key=template_key)
    await state.set_state(OrchestratorStates.waiting_goal)
    if callback.message:
        await callback.message.edit_text(
            "Шаг 2/2: отправьте короткую цель ассистента одним сообщением.\n"
            "Это необязательно — можно нажать «Пропустить».",
            reply_markup=_goal_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "orc:goal_skip")
async def orc_skip_goal(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_internal_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await state.update_data(goal_text=None)
    await state.set_state(OrchestratorStates.waiting_confirm)
    data = await state.get_data()
    template_title = _TEMPLATES.get(data.get("template_key", ""), "—")
    if callback.message:
        await callback.message.edit_text(
            f"Проверьте данные:\n"
            f"• Шаблон: {template_title}\n"
            "• Цель: —\n\n"
            "Подтверждаете создание?",
            reply_markup=_confirm_kb(),
        )
    await callback.answer()


@router.message(StateFilter(OrchestratorStates.waiting_goal), F.text)
async def orc_goal_text(message: Message, state: FSMContext) -> None:
    goal_text = (message.text or "").strip()
    if not goal_text:
        await message.answer("Пусто. Отправьте цель текстом, нажмите «Пропустить» или /cancel.")
        return

    goal_text = goal_text[:300]
    await state.update_data(goal_text=goal_text)
    await state.set_state(OrchestratorStates.waiting_confirm)
    data = await state.get_data()
    template_title = _TEMPLATES.get(data.get("template_key", ""), "—")
    await message.answer(
        f"Проверьте данные:\n"
        f"• Шаблон: {template_title}\n"
        f"• Цель: {goal_text}\n\n"
        "Подтверждаете создание?",
        reply_markup=_confirm_kb(),
    )


@router.callback_query(F.data == "orc:confirm")
async def orc_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_internal_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    data = await state.get_data()
    template_key = data.get("template_key")
    if template_key not in _TEMPLATES:
        await state.clear()
        if callback.message:
            await callback.message.answer("Шаблон не выбран. Запустите заново: /create_assistant")
        await callback.answer()
        return

    goal_text = data.get("goal_text")
    async with SessionLocal() as session:
        job_id = await provisioning_service.create_assistant_job(
            session=session,
            owner_user_id=callback.from_user.id,
            template_key=template_key,
            goal_text=goal_text,
        )
    # MVP: запускаем обработку сразу, пока нет отдельного фонового worker-процесса.
    async with SessionLocal() as session:
        await provisioning_service.run_next_job(session)

    await record_event(
        "assistant_provision_job_created",
        user_id=callback.from_user.id,
        payload={"job_id": job_id, "template_key": template_key},
    )
    await state.clear()
    msg = (
        f"Заявка принята: <code>job-{job_id}</code>\n"
        "Настройка запущена. Проверьте прогресс командой /jobs и список ассистентов /my_assistants."
    )
    if callback.message:
        await callback.message.edit_text(msg)
    else:
        await callback.bot.send_message(callback.from_user.id, msg)
    await callback.answer("Запустили настройку")


@router.message(Command("my_assistants"))
async def cmd_my_assistants(message: Message) -> None:
    if not await _check_internal_access(message.from_user.id):
        await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
        return

    async with SessionLocal() as session:
        rows = await session.execute(
            text(
                """
                SELECT id, name, status, template_key, route_mode
                FROM assistant_instances
                WHERE owner_user_id = :owner_user_id
                ORDER BY id DESC
                LIMIT 20
                """
            ),
            {"owner_user_id": message.from_user.id},
        )
        assistants = rows.mappings().all()

    if not assistants:
        await message.answer("Пока нет созданных ассистентов. Начните с /create_assistant")
        return

    lines = ["Ваши ассистенты:"]
    for item in assistants:
        lines.append(
            f"• #{item['id']} {item['name']} — {item['status']} "
            f"(шаблон: {item['template_key']}, route: {item['route_mode']})"
        )
    await message.answer("\n".join(lines))


@router.message(Command("jobs"))
async def cmd_jobs(message: Message) -> None:
    if not await _check_internal_access(message.from_user.id):
        await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
        return

    async with SessionLocal() as session:
        jobs = await provisioning_service.get_user_jobs(session, owner_user_id=message.from_user.id, limit=10)

    if not jobs:
        await message.answer("Заявок пока нет. Создайте ассистента через /create_assistant")
        return

    lines = ["Последние заявки:"]
    for job in jobs:
        suffix = f" — {job['error_message']}" if job.get("error_message") else ""
        lines.append(f"• job-{job['id']}: {job['status']} (шаблон: {job['template_key']}){suffix}")
    await message.answer("\n".join(lines))


@router.message(
    StateFilter(OrchestratorStates.waiting_goal, OrchestratorStates.waiting_confirm),
    Command("cancel"),
)
async def orc_cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание ассистента отменено.", reply_markup=main_menu_reply_keyboard())


@router.callback_query(F.data == "orc:cancel")
async def orc_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Создание ассистента отменено.")
    await callback.answer()
