from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from models.payment import Payment
from services.yookassa_client import create_payment


async def create_subscription_checkout_url(
    session: AsyncSession,
    settings: Settings,
    *,
    user_id: int,
    plan: str,
    llm_line: str,
) -> str:
    if not settings.yukassa_configured:
        raise RuntimeError("ЮKassa не настроена (YUKASSA_SHOP_ID / YUKASSA_SECRET_KEY).")

    plan_key = plan.strip().lower()
    line_key = llm_line.strip().lower()
    if line_key not in ("gpt", "claude", "gemini"):
        raise ValueError("llm_line must be gpt, claude or gemini")
    if plan_key not in ("basic", "standard", "pro"):
        raise ValueError("plan must be basic, standard or pro")

    amount = settings.billing_amount_rub(line_key, plan_key)
    metadata = {
        "telegram_user_id": str(user_id),
        "plan": plan_key,
        "llm_line": line_key,
    }
    data = await create_payment(
        settings,
        amount_value=amount,
        currency=settings.yukassa_currency,
        return_url=settings.billing_return_url,
        description=f"Подписка — {line_key.upper()} / {plan_key}",
        metadata=metadata,
    )
    y_pid = data["id"]
    conf = data.get("confirmation") or {}
    url = conf.get("confirmation_url")
    if not url:
        raise RuntimeError("ЮKassa не вернула confirmation_url")

    amt = (data.get("amount") or {}).get("value", amount)
    cur = (data.get("amount") or {}).get("currency", settings.yukassa_currency)

    row = Payment(
        user_id=user_id,
        yookassa_payment_id=y_pid,
        status="pending",
        amount_value=str(amt),
        currency=str(cur),
        plan=plan_key,
        llm_line=line_key,
    )
    session.add(row)
    await session.commit()
    return url
