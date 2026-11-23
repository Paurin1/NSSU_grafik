"""Date helpers; all dates are ``datetime.date`` objects."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

POLISH_WEEKDAYS = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)


def month_days(year: int, month: int) -> list[date]:
    """All calendar days of the month (leap years handled by ``calendar``)."""
    days_in_month = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, days_in_month + 1)]


def weekday_name_pl(day: date) -> str:
    return POLISH_WEEKDAYS[day.weekday()]


def days_before(day: date, count: int) -> list[date]:
    """The ``count`` days preceding ``day`` (oldest first)."""
    return [day - timedelta(days=offset) for offset in range(count, 0, -1)]


def next_month_range(year: int, month: int) -> tuple[date, date]:
    """First and last day of the month following ``year``/``month``."""
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    days = month_days(next_year, next_month)
    return days[0], days[-1]
