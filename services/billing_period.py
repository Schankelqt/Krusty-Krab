"""Биллинговый период: от числа оплаты до того же числа следующего месяца (границы по UTC-календарю)."""

from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta


def subscription_window_from_payment(paid_at: datetime | None = None) -> tuple[datetime, datetime]:
    """
    [start, end): начало — 00:00 UTC в день оплаты, конец — 00:00 UTC в тот же календарный день
    следующего месяца.
    """
    if paid_at is None:
        paid_at = datetime.now(timezone.utc)
    elif paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=timezone.utc)
    else:
        paid_at = paid_at.astimezone(timezone.utc)

    start = paid_at.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + relativedelta(months=1)
    return start, end
