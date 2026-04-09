from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.menu import main_menu_reply_keyboard
from core.config import get_settings
from core.database import SessionLocal
from models.user import User
from services.metrics_service import record_event
from services.team_notifications import notify_team_html
from services.user_service import UserService

router = Router()

_ONB_STEP1 = (
    "<b>Добро пожаловать.</b>\n\n"
    "Здесь персональный AI-ассистент в Telegram: ответы на вопросы, тексты и идеи "
    "в рамках вашего тарифа и лимитов.\n\n"
    "Дальше — как устроен доступ: триал, подписка и мягкий режим."
)

_ONB_STEP2 = (
    "<b>Как пользоваться</b>\n\n"
    "• <b>Триал</b> — бесплатное знакомство с ассистентом на ограниченное время и число сообщений.\n"
    "• <b>Тарифы</b> — платные пакеты токенов (разные линии моделей: GPT, Claude, Gemini).\n"
    "• После триала без подписки доступен <b>мягкий режим</b>: несколько ответов в день.\n\n"
    "Нажмите «В меню», чтобы открыть кнопки внизу экрана."
)


def _onb_kb_next() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Далее →", callback_data="onb:s2")],
        ]
    )


def _onb_kb_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✓ В меню", callback_data="onb:done")],
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    settings = get_settings()
    is_new = False
    async with SessionLocal() as session:
        user_service = UserService(session)
        user, is_new = await user_service.get_or_create(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        onboarding_done = user.onboarding_completed

    await record_event("command_start", user_id=message.from_user.id)

    if is_new:
        uname = f"@{message.from_user.username}" if message.from_user.username else "—"
        await notify_team_html(
            f"Новый пользователь: <code>{message.from_user.id}</code> {uname}\n"
            f"Имя: {message.from_user.first_name or '—'}",
            kind="user",
        )

    if not onboarding_done:
        await message.answer(_ONB_STEP1, reply_markup=_onb_kb_next())
        return

    await _send_main_welcome(message, settings)


@router.callback_query(F.data == "onb:s2")
async def onb_step2(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    await callback.message.edit_text(_ONB_STEP2, reply_markup=_onb_kb_done())
    await callback.answer()


@router.callback_query(F.data == "onb:done")
async def onb_done(callback: CallbackQuery) -> None:
    settings = get_settings()
    uid = callback.from_user.id
    async with SessionLocal() as session:
        user = await session.get(User, uid)
        if user:
            user.onboarding_completed = True
            await session.commit()
    await callback.answer()
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass
    text = (
        "Готово. Используйте кнопки меню внизу — или /help.\n\n"
        "С чего начать:\n\n"
        f"• {settings.btn_trial} — пробный период.\n"
        f"• {settings.btn_plans} — выбор линии модели и пакета токенов.\n"
        "• /tokens — ваши лимиты.\n\n"
        "Пишите обычным текстом в чат, когда доступ открыт."
    )
    await callback.bot.send_message(uid, text, reply_markup=main_menu_reply_keyboard())


async def _send_main_welcome(message: Message | None, settings) -> None:
    if message is None:
        return
    text = (
        "С чего начать:\n\n"
        f"• {settings.btn_trial} — пробный период.\n"
        f"• {settings.btn_plans} — выбор линии модели и пакета токенов.\n"
        "• /tokens — ваши лимиты.\n\n"
        "Пишите обычным текстом в чат, когда доступ открыт."
    )
    await message.answer(text, reply_markup=main_menu_reply_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    settings = get_settings()
    await message.answer(
        "Команды:\n"
        "/start — приветствие и меню\n"
        "/help — эта справка\n"
        "/tokens — лимиты (триал / подписка / токены пакета)\n"
        "/admin — панель настроек (только администраторы)\n\n"
        f"Кнопки: «{settings.btn_trial}», «{settings.btn_plans}»."
    )
