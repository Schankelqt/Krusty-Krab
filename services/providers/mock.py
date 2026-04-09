from services.providers.base import LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    provider_name = "mock"

    async def generate(self, prompt: str, user_id: int) -> LLMResponse:
        safe_prompt = prompt.strip().replace("\n", " ")
        if len(safe_prompt) > 120:
            safe_prompt = safe_prompt[:117] + "..."
        return LLMResponse(
            text=f"[MOCK] user={user_id} | Получен запрос: {safe_prompt}",
            model="mock-v1",
            provider=self.provider_name,
            tokens_in=max(1, len(prompt) // 4),
            tokens_out=40,
        )
