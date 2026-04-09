from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.config import get_settings
from core.database import SessionLocal
from services.subscription_service import activate_paid_subscription
from services.user_service import UserService

router = Router()


@router.message(Command("admin_grant"))
async def admin_grant(message: Message) -> None:
    settings = get_settings()
    actor_id = message.from_user.id
    if actor_id not in settings.admin_id_set:
        await message.answer("Нет доступа к admin-командам.")
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /admin_grant <telegram_user_id>")
        return

    user_id = int(parts[1])
    async with SessionLocal() as session:
        user_service = UserService(session)
        user = await user_service.get(user_id)
        if not user:
            await message.answer("Пользователь не найден в базе. Пусть сначала отправит /start.")
            return
        await activate_paid_subscription(session, user_id)
        await session.commit()

    await message.answer(f"Пользователь {user_id} активирован.")
