import httpx

from core.config import get_settings
from services.providers.base import LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate(self, prompt: str, user_id: int) -> LLMResponse:
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        model = self.settings.gemini_model.strip()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()

        text = ""
        cands = data.get("candidates") or []
        if cands:
            parts = (cands[0].get("content") or {}).get("parts") or []
            for p in parts:
                if isinstance(p, dict) and "text" in p:
                    text += str(p["text"])
        text = text.strip() or "Пустой ответ от Gemini."

        meta = data.get("usageMetadata") or {}
        tokens_in = int(meta.get("promptTokenCount", 0) or 0)
        tokens_out = int(meta.get("candidatesTokenCount", 0) or 0)
        return LLMResponse(
            text=text,
            model=model,
            provider=self.provider_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
