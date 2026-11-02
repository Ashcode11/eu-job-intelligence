from datetime import UTC, datetime

from workers.tasks.discovery import is_due


def test_daily_cron_due_after_six():
    last = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    assert not is_due("0 6 * * *", last, datetime(2026, 11, 2, 5, 59, tzinfo=UTC))
    assert is_due("0 6 * * *", last, datetime(2026, 11, 2, 6, 0, tzinfo=UTC))


def test_invalid_cron_never_due():
    assert not is_due("not a cron", datetime(2020, 1, 1, tzinfo=UTC), datetime.now(UTC))
