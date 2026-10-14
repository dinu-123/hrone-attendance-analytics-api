from datetime import datetime, timezone, timedelta

from app.main import (
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
    datetime_to_epoch_ms,
)

UTC = timezone.utc


def test_late_grace_period_is_strictly_more_than_ten_minutes():
    attendance_date = "2026-10-14"

    # 09:40:00 IST is exactly ten minutes after a 09:30 shift.
    at_grace_limit = datetime(2026, 10, 14, 4, 10, 0, tzinfo=UTC)
    assert compute_late_minutes(
        at_grace_limit, "09:30", attendance_date
    ) == 0

    # One second beyond the grace period gives ten whole late minutes.
    beyond_grace = datetime(2026, 10, 14, 4, 10, 1, tzinfo=UTC)
    assert compute_late_minutes(
        beyond_grace, "09:30", attendance_date
    ) == 10


def test_late_minutes_are_floored_from_shift_start():
    # 10:15:59 IST is 45 minutes and 59 seconds after a 09:30 shift.
    punch = datetime(2026, 10, 14, 4, 45, 59, tzinfo=UTC)

    assert compute_late_minutes(
        punch, "09:30", "2026-10-14"
    ) == 45


def test_work_hours_use_half_up_rounding():
    punch_in = datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC)
    punch_out = punch_in + timedelta(seconds=3618)  # Exactly 1.005 hours

    assert compute_work_hours(punch_in, punch_out) == 1.01


def test_overtime_below_thirty_minutes_is_zero():
    shift_date = "2026-10-14"

    # Shift ends at 18:30 IST, equivalent to 13:00 UTC.
    punch_out = datetime(2026, 10, 14, 13, 29, 59, tzinfo=UTC)

    assert compute_overtime(
        punch_out, "18:30", shift_date, "09:30"
    ) == 0


def test_overtime_at_thirty_minutes_is_counted():
    punch_out = datetime(2026, 10, 14, 13, 30, 0, tzinfo=UTC)

    assert compute_overtime(
        punch_out, "18:30", "2026-10-14", "09:30"
    ) == 30


def test_overnight_overtime_uses_next_day_shift_end():
    # A 22:00-06:00 shift starting Oct 13 ends at 06:00 IST on Oct 14.
    punch_out = datetime(2026, 10, 14, 1, 10, 0, tzinfo=UTC)

    assert compute_overtime(
        punch_out, "06:00", "2026-10-13", "22:00"
    ) == 40


def test_epoch_milliseconds_truncate_fractional_seconds():
    value = datetime(
        2026, 10, 14, 0, 0, 0, 999000, tzinfo=UTC
    )

    expected = int(
        datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC).timestamp()
    ) * 1000

    assert datetime_to_epoch_ms(value) == expected
