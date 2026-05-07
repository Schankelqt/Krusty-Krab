from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.config import get_settings
from core.database import SessionLocal
from services import provisioning_service
from services.app_config import is_internal_access_allowed
from services.metrics_service import record_event

router = Router()


class ConsultantButtonFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return (message.text or "").strip() == get_settings().btn_consultant


class QuickStartStates(StatesGroup):
    waiting_niche = State()
    waiting_goal = State()
    waiting_output = State()


def _quick_recommend_template(goal_text: str, output_text: str) -> str:
    g = goal_text.lower()
    o = output_text.lower()
    if any(k in g for k in ("продаж", "лид", "заявк", "воронк", "конвер")):
        return "sales"
    if any(k in g for k in ("поддерж", "саппорт", "faq", "вопрос", "клиент")):
        return "support"
    if any(k in o for k in ("видео", "рилс", "шорт", "пост", "контент", "сценар")):
        return "content"
    return "custom"


def _template_label(key: str) -> str:
    return {
        "content": "Контент",
        "sales": "Продажи",
        "support": "Поддержка",
        "custom": "Кастом",
    }.get(key, key)


def _guide_text() -> str:
    s = get_settings()
    return (
        "<b>Как работать с ботом (быстрый старт)</b>\n\n"
        "1) Нажмите кнопку триала или получите доступ от администратора.\n"
        f"2) Для оплаты используйте «{s.btn_plans}».\n"
        "3) Для персонализации ответов откройте /agent.\n"
        "4) Чтобы бот сам настроил нового ассистента — /create_assistant.\n\n"
        "<b>Что дальше после создания ассистента</b>\n"
        "• /jobs — статус настройки\n"
        "• /my_assistants — список ваших ассистентов\n"
        "• Пишите обычным текстом в чат, когда доступ открыт.\n\n"
        "Ниже можно автоматически создать ассистента-консультанта."
    )


def _guide_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Быстрый запуск (3 вопроса)", callback_data="cg:brief_start")],
            [InlineKeyboardButton(text="📦 Каталог бизнес-пакетов", callback_data="cg:packages")],
            [InlineKeyboardButton(text="🛠 Создать ассистента-консультанта", callback_data="cg:create_support")],
            [InlineKeyboardButton(text="🧩 Открыть мастер ассистента", callback_data="cg:hint_create")],
        ]
    )


async def _check_access(user_id: int) -> bool:
    settings = get_settings()
    async with SessionLocal() as session:
        return await is_internal_access_allowed(user_id, settings, session)


@router.message(Command("guide"))
@router.message(Command("consult"))
async def cmd_guide(message: Message) -> None:
    if not await _check_access(message.from_user.id):
        await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
        return
    await message.answer(_guide_text(), reply_markup=_guide_kb())


@router.message(ConsultantButtonFilter())
async def consultant_button(message: Message) -> None:
    if not await _check_access(message.from_user.id):
        await message.answer("Доступ ограничен (режим внутреннего теста). Обратитесь к администратору.")
        return
    await message.answer(_guide_text(), reply_markup=_guide_kb())


@router.callback_query(F.data == "cg:hint_create")
async def cb_hint_create(callback: CallbackQuery) -> None:
    if not await _check_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    text = (
        "Запустите мастер: <code>/create_assistant</code>\n"
        "Дальше: шаблон → цель → подтверждение.\n"
        "Прогресс: <code>/jobs</code>, результат: <code>/my_assistants</code>."
    )
    if callback.message:
        await callback.message.answer(text)
    await callback.answer()


def _packages_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧠 Контент-пакет", callback_data="cg:pkg:content")],
            [InlineKeyboardButton(text="💰 Sales-пакет", callback_data="cg:pkg:sales")],
            [InlineKeyboardButton(text="🛟 Support-пакет", callback_data="cg:pkg:support")],
            [InlineKeyboardButton(text="« Назад", callback_data="cg:pkg_back")],
        ]
    )


def _package_text(key: str) -> tuple[str, str]:
    if key == "content":
        return (
            "Контент-пакет",
            "Подойдёт, если вам нужно регулярно выпускать контент.\n\n"
            "Что получите:\n"
            "• Генерация идей и контент-планов\n"
            "• Черновики постов/сценариев/структур\n"
            "• Единый стиль подачи и быстрые итерации",
        )
    if key == "sales":
        return (
            "Sales-пакет",
            "Подойдёт для лидогенерации и коммуникации с клиентами.\n\n"
            "Что получите:\n"
            "• Скрипты переписок и квалификация лида\n"
            "• Офферы под сегменты аудитории\n"
            "• Шаблоны ответов для конверсии",
        )
    return (
        "Support-пакет",
        "Подойдёт для FAQ и первичной клиентской поддержки.\n\n"
        "Что получите:\n"
        "• Быстрые ответы на частые вопросы\n"
        "• Снижение нагрузки на ручную поддержку\n"
        "• Единый стандарт тона и качества ответа",
    )


def _package_confirm_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подключить этот пакет", callback_data=f"cg:pkg_apply:{key}")],
            [InlineKeyboardButton(text="📦 К другим пакетам", callback_data="cg:packages")],
        ]
    )


@router.callback_query(F.data == "cg:packages")
async def cb_packages(callback: CallbackQuery) -> None:
    if not await _check_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            "<b>Каталог бизнес-пакетов</b>\n"
            "Выберите пакет под вашу задачу. Бот сам создаст и настроит ассистента.",
            reply_markup=_packages_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "cg:pkg_back")
async def cb_pkg_back(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer(_guide_text(), reply_markup=_guide_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("cg:pkg:"))
async def cb_pkg_show(callback: CallbackQuery) -> None:
    if not await _check_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    key = (callback.data or "").split(":")[-1]
    if key not in {"content", "sales", "support"}:
        await callback.answer()
        return
    title, body = _package_text(key)
    if callback.message:
        await callback.message.answer(
            f"<b>{title}</b>\n\n{body}",
            reply_markup=_package_confirm_kb(key),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("cg:pkg_apply:"))
async def cb_pkg_apply(callback: CallbackQuery) -> None:
    if not await _check_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    key = (callback.data or "").split(":")[-1]
    if key not in {"content", "sales", "support"}:
        await callback.answer()
        return
    goal_map = {
        "content": "Готовит контент-план, черновики постов и сценарии в нужном стиле.",
        "sales": "Помогает с лидогенерацией, скриптами продаж и ответами для конверсии.",
        "support": "Закрывает первичные вопросы клиентов и ведёт FAQ-поддержку.",
    }
    async with SessionLocal() as session:
        job_id = await provisioning_service.create_assistant_job(
            session=session,
            owner_user_id=callback.from_user.id,
            template_key=key,
            goal_text=goal_map[key],
        )
    async with SessionLocal() as session:
        await provisioning_service.run_next_job(session)
    await record_event(
        "package_assistant_autocreate",
        user_id=callback.from_user.id,
        payload={"job_id": job_id, "template": key},
    )
    if callback.message:
        await callback.message.answer(
            f"Пакет подключён. Создана заявка <code>job-{job_id}</code> "
            f"(шаблон: {_template_label(key)}).\nПроверьте: /jobs и /my_assistants"
        )
    await callback.answer("Готово")


@router.callback_query(F.data == "cg:create_support")
async def cb_create_support(callback: CallbackQuery) -> None:
    if not await _check_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    goal = "Консультирует пользователя по продукту, командам и первичной настройке."
    async with SessionLocal() as session:
        job_id = await provisioning_service.create_assistant_job(
            session=session,
            owner_user_id=callback.from_user.id,
            template_key="support",
            goal_text=goal,
        )
    async with SessionLocal() as session:
        await provisioning_service.run_next_job(session)

    await record_event(
        "support_assistant_autocreate",
        user_id=callback.from_user.id,
        payload={"job_id": job_id},
    )

    if callback.message:
        await callback.message.answer(
            f"Готово. Создана заявка <code>job-{job_id}</code> на ассистента-консультанта.\n"
            "Проверьте: /jobs и /my_assistants"
        )
    await callback.answer("Запущено")


@router.callback_query(F.data == "cg:brief_start")
async def cb_brief_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await state.set_state(QuickStartStates.waiting_niche)
    if callback.message:
        await callback.message.answer(
            "<b>Быстрый запуск</b> (1/3)\n"
            "Опишите нишу/тему вашего проекта (например: онлайн-школа английского)."
        )
    await callback.answer()


@router.message(StateFilter(QuickStartStates.waiting_niche), F.text)
async def quick_niche(message: Message, state: FSMContext) -> None:
    niche = (message.text or "").strip()
    if not niche:
        await message.answer("Нужно коротко описать нишу. Или /cancel.")
        return
    await state.update_data(niche=niche[:180])
    await state.set_state(QuickStartStates.waiting_goal)
    await message.answer(
        "<b>Быстрый запуск</b> (2/3)\n"
        "Какая главная задача ассистента? (продажи, поддержка, контент, аналитика...)"
    )


@router.message(StateFilter(QuickStartStates.waiting_goal), F.text)
async def quick_goal(message: Message, state: FSMContext) -> None:
    goal = (message.text or "").strip()
    if not goal:
        await message.answer("Нужно описать задачу ассистента. Или /cancel.")
        return
    await state.update_data(goal=goal[:240])
    await state.set_state(QuickStartStates.waiting_output)
    await message.answer(
        "<b>Быстрый запуск</b> (3/3)\n"
        "Какой результат вы хотите получать чаще всего? (ответы клиентам, посты, скрипты, отчёты...)"
    )


@router.message(StateFilter(QuickStartStates.waiting_output), F.text)
async def quick_output(message: Message, state: FSMContext) -> None:
    output = (message.text or "").strip()
    if not output:
        await message.answer("Нужно описать ожидаемый результат. Или /cancel.")
        return
    data = await state.get_data()
    niche = str(data.get("niche", "")).strip()
    goal = str(data.get("goal", "")).strip()
    result = output[:240]
    template = _quick_recommend_template(goal, result)
    goal_text = (
        f"Ниша: {niche}. "
        f"Главная задача: {goal}. "
        f"Ожидаемый результат: {result}."
    )
    await state.update_data(recommended_template=template, final_goal=goal_text)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать по рекомендации", callback_data="cg:brief_confirm")],
            [InlineKeyboardButton(text="🧩 Открыть мастер вручную", callback_data="cg:hint_create")],
            [InlineKeyboardButton(text="Отмена", callback_data="cg:brief_cancel")],
        ]
    )
    await message.answer(
        "<b>Рекомендация готова</b>\n"
        f"• Шаблон: <b>{_template_label(template)}</b>\n"
        "• Конфигурация собрана из ваших ответов.\n\n"
        "Если согласны — бот сразу запустит настройку.",
        reply_markup=kb,
    )


@router.callback_query(F.data == "cg:brief_confirm")
async def cb_brief_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_access(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    data = await state.get_data()
    template = str(data.get("recommended_template", "custom"))
    goal_text = str(data.get("final_goal", "")).strip() or "Создано через быстрый запуск."
    async with SessionLocal() as session:
        job_id = await provisioning_service.create_assistant_job(
            session=session,
            owner_user_id=callback.from_user.id,
            template_key=template,
            goal_text=goal_text,
        )
    async with SessionLocal() as session:
        await provisioning_service.run_next_job(session)
    await record_event(
        "quickstart_assistant_autocreate",
        user_id=callback.from_user.id,
        payload={"job_id": job_id, "template": template},
    )
    await state.clear()
    if callback.message:
        await callback.message.answer(
            f"Готово. Создана заявка <code>job-{job_id}</code> (шаблон: {_template_label(template)}).\n"
            "Проверьте: /jobs и /my_assistants"
        )
    await callback.answer("Запущено")


@router.callback_query(F.data == "cg:brief_cancel")
async def cb_brief_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.answer("Быстрый запуск отменён.")
    await callback.answer()


@router.message(
    StateFilter(
        QuickStartStates.waiting_niche,
        QuickStartStates.waiting_goal,
        QuickStartStates.waiting_output,
    ),
    Command("cancel"),
)
async def quick_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Быстрый запуск отменён.")
