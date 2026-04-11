import httpx

from core.config import get_settings
from services.providers.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, prompt: str, user_id: int, *, user=None) -> LLMResponse:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        payload = {
            "model": self.settings.openai_model,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}

        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        text = data.get("output_text", "") or "Пустой ответ от модели."
        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            model=self.settings.openai_model,
            provider=self.provider_name,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
        )
