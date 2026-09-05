"""Unit: POLL-02 / POLL-03 / POLL-05 — the per-source clamp on the tier (D-57, D-58).

`effective_interval_seconds` is `min(tier, baseline)` raised to the per-source floor, and
each half of that sentence is a separate promise:

* `min` and not `max` — watches may only speed polling UP. OpenTable's baseline and minimum
  are BOTH 90 s, so ten watches must not drag POLL-03's heatmap collection cadence down.
* the floor is applied LAST — POLL-05 promises Resy no more than one request per 45 s per
  restaurant per context, and no baseline argument, tier or admin override may buy a rate
  below it.

Every expected value is a literal.
"""
from __future__ import annotations

import pytest

from shared.redis_keys import (
    POLL_INTERVAL_SECONDS,
    RESY_BASELINE_INTERVAL_SECONDS_DEFAULT,
    RESY_MIN_INTERVAL_SECONDS,
    effective_interval_seconds,
)


def test_the_constants_this_file_pins_are_the_documented_ones():
    """Guard the guard: these three numbers are the whole clamp."""
    assert POLL_INTERVAL_SECONDS == 90
    assert RESY_BASELINE_INTERVAL_SECONDS_DEFAULT == 180
    assert RESY_MIN_INTERVAL_SECONDS == 45


# --------------------------------------------------------------------------------------
# OpenTable — POLL-03's 90 s cadence is fixed in BOTH directions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("active_watches", [1000, 100, 12, 10, 9, 3, 2, 1, 0])
def test_opentable_always_polls_at_ninety_seconds(active_watches):
    """Watches may only speed a source up, and OpenTable is already at its floor.

    A 60 s OpenTable poll would break POLL-03's heatmap collection cadence, whose whole
    value is that every restaurant is sampled on the SAME interval — a mixed-rate heatmap
    silently over-weights the busiest restaurants.
    """
    assert effective_interval_seconds("opentable", active_watches) == 90


# --------------------------------------------------------------------------------------
# Resy — the 180 s baseline and the 45 s floor
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "active_watches, expected",
    [
        (100, 60),   # tier 1 (60) beats the 180 baseline, and clears the 45 floor
        (10, 60),    # tier boundary
        (9, 180),    # tier 2 equals the baseline
        (5, 180),
        (3, 180),    # tier boundary
        (2, 180),    # tier 3 (600) loses to the 180 baseline: min(), not max()
        (0, 180),    # D-58 default of no watches
    ],
)
def test_resy_uses_the_tier_but_never_slower_than_its_baseline(active_watches, expected):
    assert effective_interval_seconds("resy", active_watches) == expected


@pytest.mark.parametrize(
    "baseline_seconds, active_watches, expected",
    [
        (30, 100, 45),   # a baseline below the POLL-05 floor is clamped back up
        (30, 0, 45),
        (1, 100, 45),    # an absurd baseline cannot buy a 1 s poll rate
        (45, 100, 45),   # exactly the floor
        (90, 100, 60),   # tier 1 (60) is faster than a 90 s baseline and above the floor
        (600, 100, 60),  # a generous baseline does not slow the tier down
        (600, 0, 600),   # tier 3 with a baseline that permits it
    ],
)
def test_a_caller_supplied_baseline_is_clamped_up_to_the_poll_05_floor(
    baseline_seconds, active_watches, expected
):
    """The floor is the PROMISE; the baseline is a preference. The promise is applied last."""
    assert (
        effective_interval_seconds("resy", active_watches, baseline_seconds=baseline_seconds)
        == expected
    )


# --------------------------------------------------------------------------------------
# The admin tier override (D-58)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override, active_watches, expected",
    [
        (1, 0, 60),     # override wins over a 0-watch restaurant
        (1, 100, 60),
        (2, 0, 180),
        (2, 100, 180),  # override wins over a 100-watch restaurant, slowing it down
        (3, 100, 180),  # tier 3 is 600 s, but Resy's 180 s baseline still clamps it
        (3, 0, 180),
    ],
)
def test_an_override_selects_the_tier_regardless_of_the_watch_count(
    override, active_watches, expected
):
    assert effective_interval_seconds("resy", active_watches, override=override) == expected


def test_an_override_still_passes_through_the_per_source_clamp():
    """An admin may not override the promise: tier 1 on OpenTable is still 90 s."""
    assert effective_interval_seconds("opentable", 0, override=1) == 90
    assert (
        effective_interval_seconds("resy", 0, override=1, baseline_seconds=30) == 45
    )


@pytest.mark.parametrize("override", [None, 0, 4, 99, -1])
def test_an_absent_or_out_of_range_override_falls_back_to_the_computed_tier(override):
    """An operator typo must not silently select tier 1 — the fastest, politest-to-break rate."""
    assert effective_interval_seconds("resy", 100, override=override) == 60
    assert effective_interval_seconds("resy", 0, override=override) == 180


# --------------------------------------------------------------------------------------
# Defensive: an unknown source
# --------------------------------------------------------------------------------------


def test_an_unknown_source_degrades_to_the_strictest_known_floor():
    """`AvailabilityRaw.source` is a Literal, so this is unreachable today — and must stay safe.

    An unknown source is a programming error, but raising here would crash `poll_loop`. It
    degrades to the 180 s baseline and the STRICTEST known floor (90 s, OpenTable's), so an
    unrecognised platform can never be polled faster than any recognised one is allowed.
    """
    assert effective_interval_seconds("someone_elses_platform", 100) == 90   # clamped up
    assert effective_interval_seconds("someone_elses_platform", 0) == 180    # baseline caps
    assert effective_interval_seconds("someone_elses_platform", 100) >= 90
