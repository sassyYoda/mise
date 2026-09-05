"""Unit: POLL-02 — the three tier boundaries of `tier_interval_seconds` (D-57, D-58).

REQUIREMENTS.md states the tiers literally: "Tier 1: 60s for >= 10 watches, Tier 2: 3min for
3-9 watches, Tier 3: 10min for 1-2 watches". Every expected value below is a LITERAL copied
from that sentence, never re-derived from the function under test — a test that computes its
own expectation from the implementation cannot detect a wrong implementation.

Both sides of every threshold are asserted. A test that only checked 12, 5 and 1 would pass
against `>` where the requirement says `>=`, and the resulting off-by-one is silent: a
10-watch restaurant polled at 180 s instead of 60 s never errors, it just misses tables.
"""
from __future__ import annotations

import pytest

from shared.redis_keys import TIER_INTERVALS_SECONDS, tier_interval_seconds

TIER_1_SECONDS = 60
TIER_2_SECONDS = 180
TIER_3_SECONDS = 600


@pytest.mark.parametrize(
    "active_watches, expected_seconds",
    [
        # Tier 1 — >= 10 watches
        (1000, TIER_1_SECONDS),
        (100, TIER_1_SECONDS),
        (11, TIER_1_SECONDS),
        (10, TIER_1_SECONDS),   # boundary: the requirement says >= 10, not > 10
        # Tier 2 — 3..9 watches
        (9, TIER_2_SECONDS),    # boundary: the other side of 10
        (5, TIER_2_SECONDS),
        (4, TIER_2_SECONDS),
        (3, TIER_2_SECONDS),    # boundary: the requirement says 3-9 inclusive
        # Tier 3 — 0..2 watches
        (2, TIER_3_SECONDS),    # boundary: the other side of 3
        (1, TIER_3_SECONDS),
        (0, TIER_3_SECONDS),    # D-58: an unwatched restaurant defaults to the slowest tier
    ],
)
def test_tier_interval_seconds_matches_the_literal_poll_02_tiers(active_watches, expected_seconds):
    assert tier_interval_seconds(active_watches) == expected_seconds


@pytest.mark.parametrize("active_watches", [-1, -7, -1000])
def test_a_negative_watch_count_degrades_to_the_slowest_tier_rather_than_raising(active_watches):
    """`watch:count` is written by Phase 5 and read here; a bad value may not crash poll_loop.

    Degrading to 600 s is the safe direction — a corrupt hash value must never buy a
    restaurant a FASTER poll rate than the tiers allow (T-03-09).
    """
    assert tier_interval_seconds(active_watches) == TIER_3_SECONDS


def test_the_tier_table_is_keyed_by_the_admin_override_values():
    """`tier:override` writes 1 | 2 | 3, and those select tiers 1, 2 and 3 respectively (D-58)."""
    assert TIER_INTERVALS_SECONDS == {1: 60, 2: 180, 3: 600}


def test_the_tiers_are_strictly_ordered_slowest_to_fastest():
    """A future edit that made tier 2 faster than tier 1 would invert the whole scheme."""
    assert TIER_1_SECONDS < TIER_2_SECONDS < TIER_3_SECONDS


def test_more_watches_never_produce_a_slower_interval():
    """Monotonicity across the whole 0..30 range — the property the three cases add up to."""
    intervals = [tier_interval_seconds(n) for n in range(31)]
    assert intervals == sorted(intervals, reverse=True)
