from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.user import User


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMProvider:
    provider_name: str = "base"

    async def generate(self, prompt: str, user_id: int, *, user: User | None = None) -> LLMResponse:
        raise NotImplementedError
