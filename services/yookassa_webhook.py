import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.database import SessionLocal
from models.payment import Payment
from services.subscription_service import activate_paid_subscription
from services.telegram_notify import send_telegram_user_text
from services.yookassa_client import get_payment

logger = logging.getLogger(__name__)


async def process_yookassa_notification(settings: Settings, body: dict[str, Any]) -> None:
    if body.get("type") != "notification":
        return
    event = body.get("event")
    obj = body.get("object") or {}
    payment_id = obj.get("id")
    if not payment_id:
        return

    if event == "payment.canceled":
        async with SessionLocal() as session:
            row = await _get_payment_row(session, str(payment_id))
            if row:
                row.status = "canceled"
                await session.commit()
        return

    if event != "payment.succeeded":
        return

    remote = await get_payment(settings, str(payment_id))
    if remote.get("status") != "succeeded":
        logger.warning("Webhook success event but API status=%s id=%s", remote.get("status"), payment_id)
        return

    metadata = remote.get("metadata") or {}
    amount_remote = (remote.get("amount") or {}).get("value")

    try:
        uid_meta = int(metadata.get("telegram_user_id") or 0)
    except (TypeError, ValueError):
        uid_meta = 0
    plan_meta = str(metadata.get("plan") or "").strip().lower()
    llm_line_meta = str(metadata.get("llm_line") or "").strip().lower()

    async with SessionLocal() as session:
        row = await _get_payment_row(session, str(payment_id))
        if row and row.status == "succeeded":
            return

        uid = uid_meta if uid_meta > 0 else (row.user_id if row else 0)
        if uid <= 0:
            logger.error("No telegram_user_id for payment %s", payment_id)
            return

        plan = plan_meta or (row.plan if row else settings.yukassa_plan)
        llm_line = llm_line_meta or ((row.llm_line or "").strip().lower() if row else "")

        if amount_remote is not None:
            try:
                actual_amt = Decimal(str(amount_remote))
            except InvalidOperation:
                logger.error("Invalid amount from ЮKassa for payment %s", payment_id)
                return
            if llm_line in ("gpt", "claude", "gemini") and plan in ("basic", "standard", "pro"):
                expected_amt = Decimal(settings.billing_amount_rub(llm_line, plan))
                if actual_amt != expected_amt:
                    logger.error(
                        "Billing grid amount mismatch payment=%s expected=%s actual=%s line=%s plan=%s",
                        payment_id,
                        expected_amt,
                        actual_amt,
                        llm_line,
                        plan,
                    )
                    return
            elif row and row.amount_value:
                try:
                    if actual_amt != Decimal(str(row.amount_value)):
                        logger.error("Amount mismatch for payment %s", payment_id)
                        return
                except InvalidOperation:
                    logger.error("Invalid stored amount for payment %s", payment_id)
                    return

        if row:
            row.status = "succeeded"
            if llm_line in ("gpt", "claude", "gemini"):
                row.llm_line = llm_line
            row.plan = plan

        billing_line = llm_line if llm_line in ("gpt", "claude", "gemini") else None

        try:
            await activate_paid_subscription(
                session,
                uid,
                plan=plan,
                billing_llm_line=billing_line,
            )
        except ValueError:
            logger.exception("User %s missing for payment %s", uid, payment_id)
            await session.rollback()
            return

        await session.commit()

    try:
        await send_telegram_user_text(
            uid,
            "✅ Оплата получена. Подписка активна — можно пользоваться ассистентом.",
        )
    except Exception:
        logger.exception("Failed to notify user %s", uid)


async def _get_payment_row(session: AsyncSession, yookassa_payment_id: str) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.yookassa_payment_id == yookassa_payment_id)
    )
    return result.scalar_one_or_none()
