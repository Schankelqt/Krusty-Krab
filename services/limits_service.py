from datetime import datetime, timezone

from redis.asyncio import Redis

from core.config import get_settings


class LimitsService:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.settings = get_settings()

    def _today_suffix(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def get_primary_limit(self, plan: str) -> int:
        if plan == "pro":
            return self.settings.daily_msg_limit_pro
        if plan == "standard":
            return self.settings.daily_msg_limit_standard
        return self.settings.daily_msg_limit_basic

    async def can_use_primary(self, user_id: int, plan: str) -> bool:
        key = f"limit:primary:{user_id}:{self._today_suffix()}"
        used = int(await self.redis.get(key) or 0)
        return used < await self.get_primary_limit(plan)

    async def increment_primary(self, user_id: int) -> None:
        key = f"limit:primary:{user_id}:{self._today_suffix()}"
        await self.redis.incr(key)
        await self.redis.expire(key, 86400)

    async def can_soft_daily(self, user_id: int) -> bool:
        key = f"limit:soft:{user_id}:{self._today_suffix()}"
        used = int(await self.redis.get(key) or 0)
        return used < self.settings.soft_daily_message_limit

    async def increment_soft_daily(self, user_id: int) -> None:
        key = f"limit:soft:{user_id}:{self._today_suffix()}"
        await self.redis.incr(key)
        await self.redis.expire(key, 86400)

    async def can_paid_fallback(self, user_id: int) -> bool:
        key = f"limit:paidfb:{user_id}:{self._today_suffix()}"
        used = int(await self.redis.get(key) or 0)
        return used < self.settings.paid_fallback_daily_message_limit

    async def increment_paid_fallback_daily(self, user_id: int) -> None:
        key = f"limit:paidfb:{user_id}:{self._today_suffix()}"
        await self.redis.incr(key)
        await self.redis.expire(key, 86400)
