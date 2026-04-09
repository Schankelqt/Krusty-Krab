from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMProvider:
    provider_name: str = "base"

    async def generate(self, prompt: str, user_id: int) -> LLMResponse:
        raise NotImplementedError
