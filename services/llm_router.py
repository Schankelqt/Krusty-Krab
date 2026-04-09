from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from models.user import User
from services.app_config import ProductLimits
from services.limits_service import LimitsService
from services.providers import (
    LLMResponse,
    AnthropicProvider,
    GeminiProvider,
    MockProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenClawProvider,
)


class LLMRouter:
    def __init__(
        self,
        redis_client: Redis,
        db_session: AsyncSession,
        product_limits: ProductLimits,
    ) -> None:
        self.settings = get_settings()
        self.redis = redis_client
        self.db_session = db_session
        self.limits = LimitsService(redis_client, product_limits)

        self.providers = {
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "gemini": GeminiProvider(),
            "openclaw": OpenClawProvider(),
            "ollama": OllamaProvider(),
            "mock": MockProvider(),
        }

    async def _get_provider_name(self, user: User) -> str:
        if self.settings.llm_mode == "primary":
            return self.settings.primary_provider
        if self.settings.llm_mode == "fallback":
            return self.settings.fallback_provider

        # auto mode
        if await self.limits.can_use_primary(user.id, user.plan):
            return self.settings.primary_provider
        return self.settings.fallback_provider

    async def generate(
        self,
        user: User,
        prompt: str,
        *,
        provider_name: str | None = None,
        increment_primary_daily: bool = False,
    ) -> LLMResponse:
        if provider_name is None:
            provider_name = await self._get_provider_name(user)
        provider = self.providers[provider_name]

        response = await provider.generate(prompt=prompt, user_id=user.id)

        if increment_primary_daily and provider_name == self.settings.primary_provider:
            await self.limits.increment_primary(user.id)

        return response
