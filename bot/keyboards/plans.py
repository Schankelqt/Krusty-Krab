from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.config import get_settings


def plans_inline_keyboard() -> InlineKeyboardMarkup:
    """Сетка: GPT / Claude / Gemini × пакеты 1M / 2M / 3M токенов за период."""
    s = get_settings()

    def amt(line: str, tier: str) -> str:
        return s.billing_amount_rub(line, tier)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"GPT 1M — {amt('gpt', 'basic')} ₽", callback_data="pay:gpt:basic"),
                InlineKeyboardButton(text=f"2M — {amt('gpt', 'standard')} ₽", callback_data="pay:gpt:standard"),
                InlineKeyboardButton(text=f"3M — {amt('gpt', 'pro')} ₽", callback_data="pay:gpt:pro"),
            ],
            [
                InlineKeyboardButton(
                    text=f"Claude 1M — {amt('claude', 'basic')} ₽", callback_data="pay:claude:basic"
                ),
                InlineKeyboardButton(
                    text=f"2M — {amt('claude', 'standard')} ₽", callback_data="pay:claude:standard"
                ),
                InlineKeyboardButton(text=f"3M — {amt('claude', 'pro')} ₽", callback_data="pay:claude:pro"),
            ],
            [
                InlineKeyboardButton(
                    text=f"Gemini 1M — {amt('gemini', 'basic')} ₽", callback_data="pay:gemini:basic"
                ),
                InlineKeyboardButton(
                    text=f"2M — {amt('gemini', 'standard')} ₽", callback_data="pay:gemini:standard"
                ),
                InlineKeyboardButton(
                    text=f"3M — {amt('gemini', 'pro')} ₽", callback_data="pay:gemini:pro"
                ),
            ],
        ]
    )
