"""Unit: POLL-02 — the +/- 15 % jitter band of `jittered_score_ms` (D-57).

Jitter is the only reason a fleet of pollers does not synchronise onto the same wall second
and arrive at Resy as a burst. Two things can silently break it, and a bounds-only test
catches neither:

* a stubbed-out or accidentally-constant jitter still satisfies "within +/- 15 %", so this
  file asserts that MANY DISTINCT values are produced;
* a jitter that can net negative would schedule a poll in the past, which the ZSET scheduler
  claims immediately — turning the politeness mechanism into a hot loop. Every draw is
  asserted strictly greater than `now_ms`.

The draws are seeded so a failure is reproducible rather than a once-a-month flake.
"""
from __future__ import annotations

import random

import pytest

from shared.redis_keys import POLL_JITTER_FRACTION, jittered_score_ms

NOW_MS = 1_767_000_000_000  # a fixed epoch-ms instant; nothing here reads the clock
DRAWS = 1_000


def test_the_jitter_fraction_is_the_documented_fifteen_percent():
    assert POLL_JITTER_FRACTION == 0.15


@pytest.mark.parametrize("interval_seconds", [45, 60, 90, 180, 600, 1800])
def test_every_draw_lies_inside_the_fifteen_percent_band(interval_seconds):
    random.seed(20260905)
    interval_ms = interval_seconds * 1_000
    low = NOW_MS + int(interval_ms * 0.85)
    high = NOW_MS + int(interval_ms * 1.15)

    scores = [jittered_score_ms(NOW_MS, interval_seconds) for _ in range(DRAWS)]

    assert min(scores) >= low, f"{min(scores) - NOW_MS} ms is below the -15 % bound"
    assert max(scores) <= high, f"{max(scores) - NOW_MS} ms is above the +15 % bound"


@pytest.mark.parametrize("interval_seconds", [45, 60, 90, 180, 600, 1800])
def test_no_draw_ever_schedules_a_poll_at_or_before_now(interval_seconds):
    """A score <= now_ms is claimed immediately — the jitter would become a busy loop."""
    random.seed(20260905)
    scores = [jittered_score_ms(NOW_MS, interval_seconds) for _ in range(DRAWS)]
    assert min(scores) > NOW_MS


@pytest.mark.parametrize("interval_seconds", [45, 60, 180])
def test_the_jitter_actually_varies(interval_seconds):
    """A constant would satisfy a bounds-only assertion while defeating the whole mechanism."""
    random.seed(20260905)
    scores = {jittered_score_ms(NOW_MS, interval_seconds) for _ in range(DRAWS)}
    assert len(scores) > 100, f"only {len(scores)} distinct scores in {DRAWS} draws"


def test_the_band_is_used_in_both_directions():
    """Both an early and a late draw must occur — a one-sided jitter halves the spread."""
    random.seed(20260905)
    interval_ms = 180 * 1_000
    scores = [jittered_score_ms(NOW_MS, 180) for _ in range(DRAWS)]
    assert any(s < NOW_MS + interval_ms for s in scores), "no draw landed early"
    assert any(s > NOW_MS + interval_ms for s in scores), "no draw landed late"


def test_the_same_seed_reproduces_the_same_sequence():
    """Seeded reproducibility is what makes a jitter failure debuggable rather than a flake."""
    random.seed(4242)
    first = [jittered_score_ms(NOW_MS, 60) for _ in range(20)]
    random.seed(4242)
    second = [jittered_score_ms(NOW_MS, 60) for _ in range(20)]
    assert first == second


def test_the_score_is_an_integer_millisecond():
    """A float score would render as `1.767e+12` in a ZSET member and lose millisecond precision."""
    random.seed(1)
    for _ in range(50):
        assert isinstance(jittered_score_ms(NOW_MS, 60), int)


def test_a_larger_interval_produces_a_proportionally_wider_band():
    """The band is a FRACTION of the interval, not a fixed number of milliseconds."""
    random.seed(20260905)
    narrow = [jittered_score_ms(NOW_MS, 60) - NOW_MS - 60_000 for _ in range(DRAWS)]
    random.seed(20260905)
    wide = [jittered_score_ms(NOW_MS, 600) - NOW_MS - 600_000 for _ in range(DRAWS)]
    assert max(abs(x) for x in wide) > max(abs(x) for x in narrow) * 5
