"""Агрегаты для отчёта и HTTP summary."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bot_event import BotEvent
from models.payment import Payment
from models.usage_log import UsageLog
from models.user import User


@dataclass
class MetricsSummary:
    period_start_utc: datetime
    period_end_utc: datetime
    event_counts: list[tuple[str, int]]
    usage_rows: int
    tokens_by_provider: list[tuple[str, int]]
    active_paid_users: int
    users_total: int
    payments_succeeded: int
    payments_canceled: int
    revenue_rub_approx: str


async def load_summary(session: AsyncSession, since: datetime, until: datetime) -> MetricsSummary:
    now = datetime.now(timezone.utc)
    if until > now:
        until = now

    ev_stmt = (
        select(BotEvent.event_type, func.count())
        .where(BotEvent.created_at >= since, BotEvent.created_at < until)
        .group_by(BotEvent.event_type)
        .order_by(func.count().desc())
    )
    ev_rows = (await session.execute(ev_stmt)).all()
    event_counts = [(str(r[0]), int(r[1])) for r in ev_rows]

    usage_count_stmt = select(func.count()).select_from(UsageLog).where(
        UsageLog.created_at >= since, UsageLog.created_at < until
    )
    usage_rows = int((await session.execute(usage_count_stmt)).scalar_one() or 0)

    tok_sum = func.coalesce(func.sum(UsageLog.tokens_in + UsageLog.tokens_out), 0)
    tok_stmt = (
        select(UsageLog.provider, tok_sum)
        .where(UsageLog.created_at >= since, UsageLog.created_at < until)
        .group_by(UsageLog.provider)
        .order_by(tok_sum.desc())
    )
    tok_rows = (await session.execute(tok_stmt)).all()
    tokens_by_provider = [(str(r[0]), int(r[1] or 0)) for r in tok_rows]

    paid_stmt = select(func.count()).select_from(User).where(
        User.is_active.is_(True),
        User.subscription_period_start.isnot(None),
        User.subscription_period_end.isnot(None),
        User.subscription_period_start <= now,
        User.subscription_period_end > now,
    )
    active_paid_users = int((await session.execute(paid_stmt)).scalar_one() or 0)

    total_u_stmt = select(func.count()).select_from(User)
    users_total = int((await session.execute(total_u_stmt)).scalar_one() or 0)

    pay_succ_stmt = select(func.count()).select_from(Payment).where(
        Payment.status == "succeeded",
        Payment.updated_at >= since,
        Payment.updated_at < until,
    )
    payments_succeeded = int((await session.execute(pay_succ_stmt)).scalar_one() or 0)

    pay_can_stmt = select(func.count()).select_from(Payment).where(
        Payment.status == "canceled",
        Payment.updated_at >= since,
        Payment.updated_at < until,
    )
    payments_canceled = int((await session.execute(pay_can_stmt)).scalar_one() or 0)

    pay_amt_stmt = select(Payment.amount_value).where(
        Payment.status == "succeeded",
        Payment.updated_at >= since,
        Payment.updated_at < until,
    )
    amt_rows = (await session.execute(pay_amt_stmt)).scalars().all()
    total_dec = Decimal("0")
    for v in amt_rows:
        try:
            total_dec += Decimal(str(v))
        except Exception:
            continue
    revenue_rub_approx = f"{total_dec.quantize(Decimal('0.01'))}"

    return MetricsSummary(
        period_start_utc=since,
        period_end_utc=until,
        event_counts=event_counts,
        usage_rows=usage_rows,
        tokens_by_provider=tokens_by_provider,
        active_paid_users=active_paid_users,
        users_total=users_total,
        payments_succeeded=payments_succeeded,
        payments_canceled=payments_canceled,
        revenue_rub_approx=revenue_rub_approx,
    )


def summary_to_telegram_html(m: MetricsSummary, *, title: str) -> str:
    lines: list[str] = [
        f"<b>{title}</b>",
        f"Окно UTC: {m.period_start_utc:%Y-%m-%d %H:%M} — {m.period_end_utc:%Y-%m-%d %H:%M}",
        "",
        "<b>Снимок сейчас</b>",
        f"• Пользователей в базе: {m.users_total}",
        f"• Активных в оплаченном периоде: {m.active_paid_users}",
        "",
        "<b>За окно</b>",
        f"• Успешных оплат (строк payments): {m.payments_succeeded}",
        f"• Сумма amount_value по ним (₽, строки из ЮKassa): {m.revenue_rub_approx}",
        f"• Отменённых платежей (по updated_at): {m.payments_canceled}",
        f"• Записей usage_logs (ответы LLM): {m.usage_rows}",
        "",
    ]
    if m.tokens_by_provider:
        lines.append("<b>Токены (in+out) по провайдеру</b>")
        for prov, n in m.tokens_by_provider:
            lines.append(f"• {prov}: {n:,}")
        lines.append("")
    if m.event_counts:
        lines.append("<b>События bot_events</b>")
        for et, c in m.event_counts[:40]:
            lines.append(f"• {et}: {c:,}")
        if len(m.event_counts) > 40:
            lines.append(f"• … ещё типов: {len(m.event_counts) - 40}")
    else:
        lines.append("<i>Нет событий bot_events за период.</i>")
    return "\n".join(lines)


def summary_to_json_dict(m: MetricsSummary) -> dict[str, Any]:
    return {
        "period_start_utc": m.period_start_utc.isoformat(),
        "period_end_utc": m.period_end_utc.isoformat(),
        "users_total": m.users_total,
        "active_paid_users": m.active_paid_users,
        "payments_succeeded": m.payments_succeeded,
        "payments_canceled": m.payments_canceled,
        "revenue_rub_amount_strings_sum": m.revenue_rub_approx,
        "usage_log_rows": m.usage_rows,
        "tokens_by_provider": [{"provider": p, "tokens": n} for p, n in m.tokens_by_provider],
        "event_counts": [{"event_type": e, "count": c} for e, c in m.event_counts],
    }


def chunk_telegram_html(text: str, limit: int = 4000) -> Sequence[str]:
    if len(text) <= limit:
        return (text,)
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if size + line_len > limit and buf:
            parts.append("\n".join(buf))
            buf = [line]
            size = line_len
        else:
            buf.append(line)
            size += line_len
    if buf:
        parts.append("\n".join(buf))
    return parts
