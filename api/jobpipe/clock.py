"""Dates in Sydney time, used for closing dates and the digest."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")


def sydney_today() -> date:
    return datetime.now(SYDNEY).date()
