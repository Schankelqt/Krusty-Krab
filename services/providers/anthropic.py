import httpx

from core.config import get_settings
from services.providers.base import LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    provider_name = "anthropic"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, prompt: str, user_id: int, *, user=None) -> LLMResponse:
        if not self.settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        payload = {
            "model": self.settings.anthropic_model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()

        parts = data.get("content") or []
        text = ""
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                text += p.get("text", "")
        text = text.strip() or "Пустой ответ от Claude."

        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=self.settings.anthropic_model,
            provider=self.provider_name,
            tokens_in=int(usage.get("input_tokens", 0) or 0),
            tokens_out=int(usage.get("output_tokens", 0) or 0),
        )
