from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.billing_period import subscription_window_from_payment


async def activate_paid_subscription(
    session: AsyncSession,
    user_id: int,
    *,
    paid_at: datetime | None = None,
    plan: str | None = None,
    billing_llm_line: str | None = None,
) -> None:
    """Активирует подписку: период от дня оплаты до того же числа следующего месяца (UTC)."""
    paid_at = paid_at or datetime.now(timezone.utc)
    user = await session.get(User, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    period_start, period_end = subscription_window_from_payment(paid_at)
    user.is_active = True
    if plan is not None:
        user.plan = plan
    elif not (user.plan or "").strip():
        user.plan = "basic"
    if billing_llm_line is not None and billing_llm_line.strip():
        user.billing_llm_line = billing_llm_line.strip().lower()
    user.subscription_period_start = period_start
    user.subscription_period_end = period_end
    await session.flush()
