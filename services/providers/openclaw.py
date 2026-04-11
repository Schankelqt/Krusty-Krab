import logging
import time

import httpx

from core.config import get_settings
from models.user import User
from services.openclaw_input import compose_openclaw_input, openclaw_session_key
from services.providers.base import LLMProvider, LLMResponse


def _extract_output_text(data: dict) -> str:
    if t := (data.get("output_text") or "").strip():
        return t
    parts: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for c in item.get("content", []) or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "output_text" and c.get("text"):
                    parts.append(str(c["text"]))
                elif c.get("text"):
                    parts.append(str(c["text"]))
    return "\n".join(parts).strip() or "Пустой ответ OpenClaw."


_log = logging.getLogger(__name__)


class OpenClawProvider(LLMProvider):
    provider_name = "openclaw"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, prompt: str, user_id: int, *, user: User | None = None) -> LLMResponse:
        if not self.settings.openclaw_url.strip():
            raise RuntimeError("OPENCLAW_URL is not set")
        if not self.settings.openclaw_api_key.strip():
            raise RuntimeError("OPENCLAW_API_KEY is not set")

        base = self.settings.openclaw_url.rstrip("/")
        url = f"{base}/v1/responses"
        session_user = openclaw_session_key(user, user_id) if user else f"telegram-{user_id}"
        input_text = compose_openclaw_input(user, prompt)
        payload: dict = {
            "model": self.settings.openclaw_model,
            "user": session_user,
            "input": input_text,
            # Иначе Gateway отдаёт SSE; httpx ждёт тело до конца стрима — «зависание» в боте.
            "stream": False,
        }
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.settings.openclaw_api_key}",
            "Content-Type": "application/json",
            "x-openclaw-session-key": session_user,
        }
        agent_id = self.settings.openclaw_agent_id.strip() or "main"
        headers["x-openclaw-agent-id"] = agent_id

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if self.settings.openclaw_log_timing:
            _log.info(
                "OpenClaw POST /v1/responses ok in %sms (user_id=%s, session=%s)",
                elapsed_ms,
                user_id,
                session_user,
            )

        text = _extract_output_text(data)
        usage = data.get("usage", {}) or {}
        tokens_in = int(
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or 0
        )
        tokens_out = int(
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or 0
        )
        return LLMResponse(
            text=text,
            model=self.settings.openclaw_model,
            provider=self.provider_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
