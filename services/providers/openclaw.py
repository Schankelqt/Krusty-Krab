import httpx

from core.config import get_settings
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


class OpenClawProvider(LLMProvider):
    provider_name = "openclaw"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, prompt: str, user_id: int) -> LLMResponse:
        if not self.settings.openclaw_url.strip():
            raise RuntimeError("OPENCLAW_URL is not set")
        if not self.settings.openclaw_api_key.strip():
            raise RuntimeError("OPENCLAW_API_KEY is not set")

        base = self.settings.openclaw_url.rstrip("/")
        url = f"{base}/v1/responses"
        session_user = f"telegram-{user_id}"
        payload: dict = {
            "model": self.settings.openclaw_model,
            "user": session_user,
            "input": prompt,
        }
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.settings.openclaw_api_key}",
            "Content-Type": "application/json",
            "x-openclaw-session-key": session_user,
        }
        if self.settings.openclaw_agent_id.strip():
            headers["x-openclaw-agent-id"] = self.settings.openclaw_agent_id.strip()

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

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
