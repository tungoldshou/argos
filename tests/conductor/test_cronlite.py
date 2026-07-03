"""Internal documentation."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from argos.conductor.cronlite import next_due


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int,
         hour: int = 0, minute: int = 0, second: int = 0) -> float:
    """Internal documentation."""
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestAliases:
    """Internal documentation."""

    def test_hourly_fires_at_next_whole_hour(self):
        # now = 2024-01-01 09:30:00 UTC
        now = _utc(2024, 1, 1, 9, 30, 0)
        due = next_due("@hourly", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.hour == 10
        assert dt.minute == 0

    def test_daily_fires_at_midnight(self):
        # now = 2024-01-01 09:00:00 UTC
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("@daily", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2
        assert dt.hour == 0
        assert dt.minute == 0

    def test_midnight_alias_same_as_daily(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        assert next_due("@midnight", now) == next_due("@daily", now)

    def test_weekly_fires_on_next_sunday(self):
        now = _utc(2024, 1, 1, 1, 0, 0)
        due = next_due("@weekly", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.weekday() == 6  # Python Sun=6
        assert dt.hour == 0
        assert dt.minute == 0

    def test_daily_at_midnight_already_passed(self):
        """Internal documentation."""
        now = _utc(2024, 1, 1, 0, 5, 0)
        due = next_due("@daily", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestHHMM:
    """Internal documentation."""

    def test_fires_today_if_not_yet(self):
        now = _utc(2024, 1, 1, 8, 59, 0)
        due = next_due("09:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 1
        assert dt.hour == 9
        assert dt.minute == 0

    def test_fires_tomorrow_if_passed(self):
        now = _utc(2024, 1, 1, 9, 1, 0)
        due = next_due("09:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2
        assert dt.hour == 9
        assert dt.minute == 0

    def test_fires_tomorrow_if_exactly_now(self):
        """Internal documentation."""
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("09:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2

    def test_midnight_spec(self):
        now = _utc(2024, 1, 1, 23, 59, 0)
        due = next_due("00:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2
        assert dt.hour == 0

    def test_end_of_day_spec(self):
        now = _utc(2024, 1, 1, 22, 0, 0)
        due = next_due("23:30", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.hour == 23
        assert dt.minute == 30

    def test_single_digit_hour(self):
        """Internal documentation."""
        now = _utc(2024, 1, 1, 8, 0, 0)
        due = next_due("9:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.hour == 9

    def test_invalid_hour(self):
        with pytest.raises(ValueError):
            next_due("25:00", _utc(2024, 1, 1, 0, 0, 0))

    def test_invalid_minute(self):
        with pytest.raises(ValueError):
            next_due("12:60", _utc(2024, 1, 1, 0, 0, 0))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestEvery:
    """Internal documentation."""

    def test_every_30m(self):
        now = _utc(2024, 1, 1, 9, 1, 0)
        due = next_due("every 30m", now)
        assert due > now
        assert (int(due) % 1800) == 0

    def test_every_1h(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("every 1h", now)
        assert due > now
        assert (int(due) % 3600) == 0

    def test_every_10s(self):
        now = _utc(2024, 1, 1, 9, 0, 5)
        due = next_due("every 10s", now)
        assert due > now
        assert (int(due) % 10) == 0

    def test_every_2h(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("every 2h", now)
        assert due > now
        assert (int(due) % 7200) == 0

    def test_every_case_insensitive(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due1 = next_due("every 1H", now)
        due2 = next_due("every 1h", now)
        assert due1 == due2

    def test_every_spacing_flexible(self):
        """Internal documentation."""
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("every  2 m", now)
        assert due > now

    def test_every_zero_raises(self):
        """Internal documentation."""
        with pytest.raises(ValueError):
            next_due("every 0m", _utc(2024, 1, 1, 9, 0, 0))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestFiveFieldCron:
    """Internal documentation."""

    def test_specific_minute_and_hour(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("30 9 * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.hour == 9
        assert dt.minute == 30

    def test_every_minute(self):
        now = _utc(2024, 1, 1, 9, 0, 30)
        due = next_due("* * * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.minute == 1 or (dt.minute == 0 and dt.hour == 10)  # 09:01

    def test_step_slash(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("0 */2 * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.minute == 0
        assert dt.hour % 2 == 0

    def test_specific_weekday(self):
        now = _utc(2024, 1, 1, 10, 1, 0)
        due = next_due("0 10 * * 1", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.weekday() == 0  # Python Mon=0
        assert dt.hour == 10
        assert dt.minute == 0
        assert dt.day == 8

    def test_specific_day_of_month(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("0 9 15 * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 15
        assert dt.hour == 9

    def test_specific_month(self):
        now = _utc(2024, 1, 1, 0, 0, 0)
        due = next_due("0 0 1 6 *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.month == 6
        assert dt.day == 1

    def test_cross_day_boundary(self):
        """Internal documentation."""
        now = _utc(2024, 1, 1, 23, 59, 0)
        due = next_due("0 0 * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2
        assert dt.hour == 0

    def test_cross_week_boundary(self):
        """Internal documentation."""
        now = _utc(2024, 1, 6, 12, 0, 0)
        due = next_due("0 0 * * 0", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.weekday() == 6  # Python Sun=6
        assert dt.day == 7

    def test_step_in_minutes(self):
        now = _utc(2024, 1, 1, 9, 7, 0)
        due = next_due("*/15 * * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.minute in {0, 15, 30, 45}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestInvalidSpec:
    """Internal documentation."""

    @pytest.mark.parametrize("bad_spec", [
        "",
        "not-a-cron",
        "every",
        "every abc",
        "60 * * * *",
        "* 25 * * *",
        "* * 0 * *",
        "* * 32 * *",
        "* * * 0 *",
        "* * * 13 *",
        "* * * * 7",
        "* * * *",
        "* * * * * *",
        "*/0 * * * *",
        "@monthly",
    ])
    def test_invalid_raises(self, bad_spec: str):
        with pytest.raises(ValueError, match=r".+"):
            next_due(bad_spec, _utc(2024, 1, 1, 0, 0, 0))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestClockInjection:
    """Internal documentation."""

    def test_clock_param_accepted(self):
        """Internal documentation."""
        called = []

        def fake_clock():
            called.append(1)
            return _utc(2024, 1, 1, 9, 0, 0)

        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("09:30", now, clock=fake_clock)
        assert due > now

    def test_no_real_time_import_needed(self):
        """Internal documentation."""
        fixed_now = 1_000_000.0  # 1970-01-12
        due = next_due("* * * * *", fixed_now)
        assert due > fixed_now
        assert due - fixed_now < 120
