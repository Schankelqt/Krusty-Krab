from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.usage_log import UsageLog
from services.providers.base import LLMResponse


class UsageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(self, user_id: int, prompt: str, response: LLMResponse) -> None:
        item = UsageLog(
            user_id=user_id,
            provider=response.provider,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            message_preview=prompt[:200],
        )
        self.session.add(item)
        await self.session.commit()

    async def get_user_tokens_in_period(
        self, user_id: int, period_start: datetime, period_end: datetime
    ) -> int:
        stmt = select(func.coalesce(func.sum(UsageLog.tokens_in + UsageLog.tokens_out), 0)).where(
            UsageLog.user_id == user_id,
            UsageLog.created_at >= period_start,
            UsageLog.created_at < period_end,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)
