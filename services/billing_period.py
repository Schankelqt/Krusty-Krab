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


def subscription_window_for_payment(
    paid_at: datetime | None,
    current_period_end: datetime | None,
) -> tuple[datetime, datetime]:
    """
    Окно подписки после оплаты:
    - если оплата приходит, пока ещё действует текущий период (`paid_at` < `current_period_end`),
      следующий период начинается с **конца** текущего (продление без разрыва и без усечения);
    - иначе — новое окно от даты оплаты (`subscription_window_from_payment`).
    """
    paid = paid_at or datetime.now(timezone.utc)
    if paid.tzinfo is None:
        paid = paid.replace(tzinfo=timezone.utc)
    else:
        paid = paid.astimezone(timezone.utc)

    if current_period_end is not None:
        end = current_period_end
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        else:
            end = end.astimezone(timezone.utc)
        if paid < end:
            start = end
            return start, start + relativedelta(months=1)

    return subscription_window_from_payment(paid)
