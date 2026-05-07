from __future__ import annotations

import logging
import time

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

logger = logging.getLogger(__name__)

router = Router()

_TEMPLATES: dict[str, str] = {
    "content": "Контент",
    "sales": "Продажи",
    "support": "Поддержка",
    "custom": "Кастом",
}
_MAX_GOAL_TEXT_LEN = 300
_CREATE_ASSISTANT_COOLDOWN_SECONDS = 8.0
_last_create_ts_by_user: dict[int, float] = {}

_ACCESS_DENIED_TEXT = "Доступ ограничен (режим внутреннего теста). Обратитесь к администратору."
_BUSY_TEXT = "Уже обрабатываем ваш запрос — подождите пару секунд."
_GENERIC_FAILURE_TEXT = (
    "Не удалось создать заявку. Попробуйте позже или повторите через /create_assistant."
)


async def _safe_callback_send(
    callback: CallbackQuery,
    body: str,
    *,
    edit: bool = True,
    reply_markup=None,
) -> None:
    """Resilient delivery of a reply for a callback query.

    Edits the originating message when possible, then falls back to a fresh
    reply, and finally to a direct DM. All exceptions from Telegram (stale
    message, "message is not modified", missing access) are swallowed so
    they never bubble up to the user.
    """
    if callback.message and edit:
        try:
            await callback.message.edit_text(body, reply_markup=reply_markup)
            return
        except Exception:
            logger.debug("callback edit_text failed, falling back", exc_info=True)
    if callback.message:
        try:
            await callback.message.answer(body, reply_markup=reply_markup)
            return
        except Exception:
            logger.debug("callback message.answer failed, falling back", exc_info=True)
    if callback.bot is not None and callback.from_user is not None:
        try:
            await callback.bot.send_message(
                callback.from_user.id, body, reply_markup=reply_markup
            )
        except Exception:
            logger.exception(
                "callback fallback send_message failed for user_id=%s",
                callback.from_user.id,
            )


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


def _create_cooldown_seconds_left(user_id: int) -> int:
    now = time.monotonic()
    last = _last_create_ts_by_user.get(user_id)
    if last is None:
        _last_create_ts_by_user[user_id] = now
        return 0
    elapsed = now - last
    if elapsed >= _CREATE_ASSISTANT_COOLDOWN_SECONDS:
        _last_create_ts_by_user[user_id] = now
        return 0
    return int(_CREATE_ASSISTANT_COOLDOWN_SECONDS - elapsed) + 1


@router.message(Command("create_assistant"))
async def cmd_create_assistant(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if not await _check_internal_access(message.from_user.id):
        await message.answer(_ACCESS_DENIED_TEXT)
        return

    await state.clear()
    await message.answer(
        "Создадим нового ассистента.\n\nШаг 1/2: выберите шаблон.",
        reply_markup=_template_kb(),
    )


@router.callback_query(F.data.startswith("orc:tpl:"))
async def orc_choose_template(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    if not await _check_internal_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    parts = (callback.data or "").split(":")
    template_key = parts[2] if len(parts) >= 3 else ""
    if template_key not in _TEMPLATES:
        await callback.answer()
        return

    await state.update_data(template_key=template_key)
    await state.set_state(OrchestratorStates.waiting_goal)
    await _safe_callback_send(
        callback,
        "Шаг 2/2: отправьте короткую цель ассистента одним сообщением.\n"
        "Это необязательно — можно нажать «Пропустить».",
        reply_markup=_goal_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "orc:goal_skip")
async def orc_skip_goal(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    if not await _check_internal_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await state.update_data(goal_text=None)
    await state.set_state(OrchestratorStates.waiting_confirm)
    data = await state.get_data()
    template_title = _TEMPLATES.get(data.get("template_key", ""), "—")
    await _safe_callback_send(
        callback,
        f"Проверьте данные:\n"
        f"• Шаблон: {template_title}\n"
        "• Цель: —\n\n"
        "Подтверждаете создание?",
        reply_markup=_confirm_kb(),
    )
    await callback.answer()


@router.message(StateFilter(OrchestratorStates.waiting_goal), F.text)
async def orc_goal_text(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if not await _check_internal_access(message.from_user.id):
        await state.clear()
        await message.answer(_ACCESS_DENIED_TEXT)
        return

    goal_text = (message.text or "").strip()
    if not goal_text:
        await message.answer("Пусто. Отправьте цель текстом, нажмите «Пропустить» или /cancel.")
        return

    if len(goal_text) > _MAX_GOAL_TEXT_LEN:
        await message.answer(f"Цель слишком длинная. Максимум: {_MAX_GOAL_TEXT_LEN} символов.")
        return
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
    if callback.from_user is None:
        await callback.answer()
        return
    if not await _check_internal_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    user_id = callback.from_user.id

    data = await state.get_data()
    template_key = data.get("template_key")
    if template_key not in _TEMPLATES:
        await state.clear()
        await _safe_callback_send(
            callback,
            "Шаблон не выбран. Запустите заново: /create_assistant",
            edit=False,
        )
        await callback.answer()
        return

    # Per-user re-entrancy guard: prevents duplicate jobs from rapid double-presses
    # when the cooldown window or DB writes have not yet committed.
    async with provisioning_service.acquire_user_provision_lock(user_id) as acquired:
        if not acquired:
            await callback.answer(_BUSY_TEXT)
            return

        cooldown_left = _create_cooldown_seconds_left(user_id)
        if cooldown_left > 0:
            await callback.answer(
                f"Слишком часто. Повторите через {cooldown_left} сек.",
                show_alert=True,
            )
            return

        goal_text = data.get("goal_text")
        try:
            async with SessionLocal() as session:
                if await provisioning_service.has_active_jobs_for_user(session, user_id):
                    await callback.answer(
                        "У вас уже есть активная заявка. Дождитесь завершения и проверьте /jobs.",
                        show_alert=True,
                    )
                    return
                job_id = await provisioning_service.create_assistant_job(
                    session=session,
                    owner_user_id=user_id,
                    template_key=template_key,
                    goal_text=goal_text,
                )
        except Exception:
            logger.exception(
                "create_assistant_job failed user_id=%s template=%s",
                user_id,
                template_key,
            )
            await _safe_callback_send(callback, _GENERIC_FAILURE_TEXT, edit=False)
            await callback.answer("Не удалось создать заявку", show_alert=True)
            return

        # Nudge the worker to pick up the job ASAP without blocking this callback.
        # The persistent worker loop is the source of truth for actual execution.
        provisioning_service.schedule_run_next_job()

        await record_event(
            "assistant_provision_job_created",
            user_id=user_id,
            payload={"job_id": job_id, "template_key": template_key},
        )
        await state.clear()
        msg = (
            f"Заявка принята: <code>job-{job_id}</code>\n"
            "Поставили в очередь на настройку. Проверьте прогресс командой /jobs и список ассистентов /my_assistants."
        )
        await _safe_callback_send(callback, msg)
        await callback.answer("Добавили в очередь")


@router.message(Command("my_assistants"))
async def cmd_my_assistants(message: Message) -> None:
    if message.from_user is None:
        return
    if not await _check_internal_access(message.from_user.id):
        await message.answer(_ACCESS_DENIED_TEXT)
        return

    try:
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
    except Exception:
        logger.exception("my_assistants query failed user_id=%s", message.from_user.id)
        await message.answer("Не удалось получить список. Попробуйте позже.")
        return

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
    if message.from_user is None:
        return
    if not await _check_internal_access(message.from_user.id):
        await message.answer(_ACCESS_DENIED_TEXT)
        return

    try:
        async with SessionLocal() as session:
            jobs = await provisioning_service.get_user_jobs(
                session, owner_user_id=message.from_user.id, limit=10
            )
    except Exception:
        logger.exception("get_user_jobs failed user_id=%s", message.from_user.id)
        await message.answer("Не удалось получить заявки. Попробуйте позже.")
        return

    if not jobs:
        await message.answer("Заявок пока нет. Создайте ассистента через /create_assistant")
        return

    lines = ["Последние заявки:"]
    for job in jobs:
        suffix = " — ошибка выполнения" if job.get("error_message") else ""
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
    await _safe_callback_send(callback, "Создание ассистента отменено.")
    await callback.answer()
