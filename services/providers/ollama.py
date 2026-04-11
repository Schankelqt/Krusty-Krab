import httpx

from core.config import get_settings
from services.providers.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, prompt: str, user_id: int, *, user=None) -> LLMResponse:
        payload = {"model": self.settings.ollama_model, "prompt": prompt, "stream": False}
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/generate"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        return LLMResponse(
            text=data.get("response", "Пустой ответ от Ollama."),
            model=self.settings.ollama_model,
            provider=self.provider_name,
            tokens_in=int(data.get("prompt_eval_count", 0) or 0),
            tokens_out=int(data.get("eval_count", 0) or 0),
        )
