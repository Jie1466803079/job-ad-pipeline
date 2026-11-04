from datetime import UTC, date, datetime

from jobpipe.clock import sydney_midnight


def test_sydney_midnight_follows_daylight_saving():
    assert sydney_midnight(date(2026, 10, 7)).astimezone(UTC) == datetime(2026, 10, 6, 13, 0, tzinfo=UTC)
    assert sydney_midnight(date(2026, 7, 1)).astimezone(UTC) == datetime(2026, 6, 30, 14, 0, tzinfo=UTC)
