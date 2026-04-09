from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.keyboards.menu import main_menu_reply_keyboard
from core.config import get_settings

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    settings = get_settings()
    text = (
        "OpenClaw — персональный ассистент в Telegram.\n\n"
        f"• {settings.btn_trial} — триал на Ollama ({settings.trial_duration_hours} ч, до {settings.trial_message_limit} сообщений).\n"
        f"• {settings.btn_plans} — тарифы и оплата (подключим OpenClaw после оплаты).\n\n"
        "После триала доступен мягкий режим: несколько ответов в день без подписки."
    )
    await message.answer(text, reply_markup=main_menu_reply_keyboard())
