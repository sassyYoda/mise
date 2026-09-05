"""Unit: POLL-02 — the exponential backoff ladder and its TTL (D-59).

POLL-02 requires "exponential backoff on 429/503". D-59 fixes the shape:
`min(interval * 2 ** n, 1800)` where `n` is the count of CONSECUTIVE failures so far, with
the backoff state key carrying a TTL of twice the value it holds.

The exact sequence is asserted, including the step at which the 1800 s ceiling engages. A
missing ceiling is not a crash: a long-banned restaurant simply drifts to a next-poll score
days out and never recovers on its own, which looks identical to "that restaurant has no
tables" on every dashboard.
"""
from __future__ import annotations

import pytest

from shared.redis_keys import BACKOFF_MAX_SECONDS, backoff_ttl_seconds, next_backoff_seconds


def test_the_ceiling_is_the_documented_thirty_minutes():
    assert BACKOFF_MAX_SECONDS == 1_800


@pytest.mark.parametrize(
    "consecutive_failures, expected_seconds",
    [
        (0, 180),    # the FIRST failure backs off by one normal interval, not by two
        (1, 360),
        (2, 720),
        (3, 1440),   # the last uncapped step: 180 * 8
        (4, 1800),   # 180 * 16 = 2880 -> capped. The ceiling engages between n=3 and n=4.
        (5, 1800),
        (10, 1800),
        (60, 1800),  # 180 * 2**60 would be astronomanical; the cap is total
    ],
)
def test_the_backoff_ladder_from_a_one_hundred_eighty_second_interval(
    consecutive_failures, expected_seconds
):
    assert next_backoff_seconds(180, consecutive_failures) == expected_seconds


@pytest.mark.parametrize(
    "interval_seconds, consecutive_failures, expected_seconds",
    [
        (45, 0, 45),     # Resy's floor as the base interval
        (45, 1, 90),
        (45, 5, 1440),
        (45, 6, 1800),   # 45 * 64 = 2880 -> capped
        (60, 0, 60),     # tier 1
        (60, 4, 960),
        (60, 5, 1800),   # 60 * 32 = 1920 -> capped
        (90, 0, 90),     # OpenTable's interval
        (90, 4, 1440),
        (90, 5, 1800),
        (600, 0, 600),   # tier 3
        (600, 2, 1800),  # 600 * 4 = 2400 -> capped
    ],
)
def test_the_ladder_is_correct_for_every_interval_the_tiers_produce(
    interval_seconds, consecutive_failures, expected_seconds
):
    assert next_backoff_seconds(interval_seconds, consecutive_failures) == expected_seconds


def test_the_backoff_never_exceeds_the_ceiling_for_any_input():
    """The property the individual rows add up to, over the whole realistic domain."""
    for interval in (45, 60, 90, 180, 600):
        for failures in range(0, 30):
            assert next_backoff_seconds(interval, failures) <= BACKOFF_MAX_SECONDS


def test_the_backoff_is_monotonically_non_decreasing():
    """Each successive failure must wait at least as long — never less."""
    ladder = [next_backoff_seconds(180, n) for n in range(12)]
    assert ladder == sorted(ladder)


@pytest.mark.parametrize("consecutive_failures", [-1, -5])
def test_a_negative_failure_count_is_treated_as_the_first_failure(consecutive_failures):
    """A corrupt counter must not produce a fractional backoff (2 ** -1 is 0.5, a float)."""
    assert next_backoff_seconds(180, consecutive_failures) == 180


@pytest.mark.parametrize("backoff_seconds", [45, 90, 180, 360, 720, 1440, 1800])
def test_the_ttl_is_exactly_twice_the_backoff_it_holds(backoff_seconds):
    """The key must outlive the delay it describes, or the failure count resets mid-wait.

    A TTL equal to the backoff would expire at almost exactly the moment the retry fires;
    the jitter band then decides whether the ladder continues or silently restarts at 1x.
    """
    assert backoff_ttl_seconds(backoff_seconds) == 2 * backoff_seconds


def test_every_ttl_in_the_ladder_is_an_integer():
    """Redis EXPIRE takes whole seconds; a float TTL is a TypeError at the call site."""
    for n in range(8):
        ttl = backoff_ttl_seconds(next_backoff_seconds(180, n))
        assert isinstance(ttl, int)
        assert ttl > 0
