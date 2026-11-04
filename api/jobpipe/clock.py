"""Dates in Sydney time, used for closing dates, the digest and the page header."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")


def sydney_today() -> date:
    return datetime.now(SYDNEY).date()


def sydney_midnight(day: date) -> datetime:
    """The moment a Sydney calendar day starts."""
    return datetime.combine(day, time.min, tzinfo=SYDNEY)
