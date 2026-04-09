from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from core.config import get_settings


def main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    s = get_settings()
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=s.btn_trial)],
            [KeyboardButton(text=s.btn_plans)],
        ],
        resize_keyboard=True,
    )
