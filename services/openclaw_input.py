"""Сборка поля input для OpenClaw Gateway с персонализацией пользователя."""

from models.user import User

_MAX_INSTRUCTIONS_CHARS = 8000


def openclaw_session_key(user: User, telegram_user_id: int) -> str:
    """Стабильный ключ сессии OpenClaw; при сбросе диалога в БД кладётся новый."""
    raw = (user.openclaw_session_id or "").strip()
    if raw:
        return raw
    return f"telegram-{telegram_user_id}"


def compose_openclaw_input(user: User | None, user_message: str) -> str:
    """
    Текст, уходящий в POST /v1/responses input.
    Инструкции и имя ассистента префиксом — без отдельного поля system в API.
    """
    msg = (user_message or "").strip()
    if user is None:
        return msg

    name = (user.agent_display_name or "").strip()
    instr = (user.agent_instructions or "").strip()
    if len(instr) > _MAX_INSTRUCTIONS_CHARS:
        instr = instr[:_MAX_INSTRUCTIONS_CHARS]

    if not name and not instr:
        return msg

    blocks: list[str] = [
        "[Персонализация пользователя — учитывай при ответе.]",
    ]
    if name:
        blocks.append(f"Имя/роль ассистента в диалоге: {name}")
    if instr:
        blocks.append("Инструкции и стиль:")
        blocks.append(instr)
    blocks.append("---")
    blocks.append("Сообщение пользователя:")
    blocks.append(msg)
    return "\n".join(blocks)
