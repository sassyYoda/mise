"""Unit: STATE-05 — New York service-time math, pinned without a container (D-48, research B-5).

``hours_before_service`` is the only place in the phase where a local timezone is applied, and
``day_of_week`` is the column Phase 6's heatmap indexes on. Both are silent-wrong-answer defects
if they drift: nothing crashes, the numbers are just wrong forever. Hence exact expectations,
including a date whose interval crosses a daylight-saving transition.

The expected values 5.0 and 29.0 are the ones 02-RESEARCH.md §Pattern 6 verified against live
``zoneinfo``. The plan text names a first sighting of ``2026-05-01T23:00Z`` for the 5.0 case,
which is arithmetically 0.0 — 19:00 in New York on that date IS 23:00Z. The first sightings
below are the ones that actually produce the verified numbers.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as dt_time

import pytest

from services.state_machine.persistence import day_of_week, hours_before_service


def _epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def test_hours_before_service_normal_day():
    """19:00 EDT on 2026-05-01 is 23:00Z; a sighting at 18:00Z is 5 hours of lead time."""
    first_seen = _epoch_ms(datetime(2026, 5, 1, 18, 0, tzinfo=UTC))
    assert hours_before_service(date(2026, 5, 1), dt_time(19, 0), first_seen) == 5.0


def test_hours_before_service_across_the_dst_transition():
    """2026-03-08 springs forward at 02:00 local; the true elapsed interval is 29 h, not 30 h.

    A naive local-clock subtraction over this window is off by exactly the lost hour, so this
    case is the regression guard for anyone who "simplifies" the zoneinfo math away.
    """
    first_seen = _epoch_ms(datetime(2026, 3, 7, 18, 0, tzinfo=UTC))
    assert hours_before_service(date(2026, 3, 8), dt_time(19, 0), first_seen) == 29.0


def test_hours_before_service_is_negative_after_the_service_time():
    """A sighting after service has passed is negative, never clamped — a real signal, not a bug."""
    first_seen = _epoch_ms(datetime(2026, 5, 2, 23, 0, tzinfo=UTC))
    assert hours_before_service(date(2026, 5, 1), dt_time(19, 0), first_seen) == -24.0


def test_service_time_uses_new_york_not_utc():
    """The offset must be applied: the same wall time in UTC would give a 4-hour smaller lead."""
    first_seen = _epoch_ms(datetime(2026, 5, 1, 18, 0, tzinfo=UTC))
    ny = hours_before_service(date(2026, 5, 1), dt_time(19, 0), first_seen)
    naive_utc = (
        datetime(2026, 5, 1, 19, 0, tzinfo=UTC) - datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    ).total_seconds() / 3600.0
    assert ny - naive_utc == 4.0


@pytest.mark.parametrize(
    ("service_date", "expected"),
    [
        (date(2026, 5, 3), 0),  # Sunday
        (date(2026, 5, 4), 1),  # Monday
        (date(2026, 5, 5), 2),
        (date(2026, 5, 6), 3),
        (date(2026, 5, 7), 4),
        (date(2026, 5, 8), 5),
        (date(2026, 5, 9), 6),  # Saturday
    ],
)
def test_day_of_week_is_zero_for_sunday(service_date: date, expected: int):
    """0=Sun .. 6=Sat, matching migration 0008's column comment and the Phase 6 y-axis (B-5)."""
    assert day_of_week(service_date) == expected


def test_day_of_week_disagrees_with_pythons_weekday():
    """Guard against a future 'simplification' to `service_date.weekday()`, which is 0=Mon."""
    sunday = date(2026, 5, 3)
    assert day_of_week(sunday) == 0
    assert sunday.weekday() == 6
