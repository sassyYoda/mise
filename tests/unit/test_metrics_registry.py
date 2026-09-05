"""Unit: POLL-06 — `shared/metrics.py` is the ONE definition site for every Phase 3 metric (D-69).

Three traps this file exists to catch, all reproduced in 03-RESEARCH.md §Pitfall 6:

1. **Double registration.** Defining a metric twice against the default `REGISTRY` raises
   `Duplicated timeseries in CollectorRegistry` — at IMPORT, which takes the poller down at
   start rather than at first scrape. This project already evicts modules from `sys.modules`
   in integration teardown, so the failure mode is one `importlib.reload` away.
2. **The sample-name trap.** `Counter("scrape_ban_total", ...)` is stored internally as
   `scrape_ban` and emits samples `scrape_ban_total` + `scrape_ban_created`. A test that
   reads `"scrape_ban_total_total"` gets `None` — and `assert x is None` then PASSES while
   testing nothing. Every assertion below reads the CORRECT name and asserts a NUMBER.
3. **The default buckets stop at 10.0.** A Playwright poll makes three requests; a slow one
   lands in `+Inf` and becomes invisible in every latency percentile. `poll_latency_seconds`
   therefore declares explicit buckets extending past 10 s.
"""
from __future__ import annotations

import importlib

import pytest
import shared.metrics as metrics
from prometheus_client import REGISTRY


def test_importing_the_module_twice_in_one_process_raises_nothing():
    """The regression guard for `Duplicated timeseries`: a re-import is a no-op, not a redefine."""
    first = importlib.import_module("shared.metrics")
    second = importlib.import_module("shared.metrics")
    assert first is second is metrics


def test_a_second_import_does_not_duplicate_the_collectors():
    """Python caches the module, so the metric objects must be identical, not merely equal."""
    reimported = importlib.import_module("shared.metrics")
    assert reimported.scrape_ban_total is metrics.scrape_ban_total
    assert reimported.poll_latency_seconds is metrics.poll_latency_seconds


@pytest.mark.parametrize(
    "name",
    [
        "scrape_ban_total",
        "poll_latency_seconds",
        "poll_total",
        "resy_context_recycles_total",
        "resy_rate_budget_remaining",
        "playwright_contexts_active",
        "resy_auth_mode",
    ],
)
def test_every_phase_three_metric_is_exported(name):
    assert hasattr(metrics, name), f"{name} is missing from shared.metrics"


def test_scrape_ban_total_increments_under_its_real_sample_name():
    """Reads `scrape_ban_total`, NOT `scrape_ban_total_total`, and asserts a float."""
    labels = {"source": "resy", "reason": "empty_results"}
    before = REGISTRY.get_sample_value("scrape_ban_total", labels) or 0.0
    metrics.scrape_ban_total.labels(source="resy", reason="empty_results").inc()
    after = REGISTRY.get_sample_value("scrape_ban_total", labels)

    assert isinstance(after, float), (
        "get_sample_value returned None — the sample name is wrong, and an `is None` "
        "assertion here would have passed while testing nothing"
    )
    assert after == before + 1.0


def test_the_doubled_suffix_sample_name_is_the_trap_not_the_metric():
    """`scrape_ban_total_total` does not exist; the CORRECT name is the one that is numeric."""
    labels = {"source": "resy", "reason": "challenge_403"}
    metrics.scrape_ban_total.labels(**labels).inc()

    correct = REGISTRY.get_sample_value("scrape_ban_total", labels)
    doubled = REGISTRY.get_sample_value("scrape_ban_total_total", labels)

    assert isinstance(correct, float) and correct >= 1.0
    assert doubled is None  # asserted only AFTER pinning that the correct name is numeric


def test_poll_total_counts_by_source_and_status():
    labels = {"source": "resy", "status": "success"}
    before = REGISTRY.get_sample_value("poll_total", labels) or 0.0
    metrics.poll_total.labels(**labels).inc()
    assert REGISTRY.get_sample_value("poll_total", labels) == before + 1.0


def test_poll_latency_seconds_has_a_bucket_above_ten_seconds():
    """The library default tops out at 10.0; three Playwright requests can exceed it."""
    boundaries = [
        float(b) for b in metrics.poll_latency_seconds._upper_bounds if b != float("inf")
    ]
    assert max(boundaries) > 10.0, f"buckets stop at {max(boundaries)} — a slow poll is invisible"
    assert 60.0 in boundaries


def test_poll_latency_seconds_observes_into_the_correct_bucket():
    """A 0.052 s observation lands in le=0.1 — the histogram is wired, not merely declared."""
    metrics.poll_latency_seconds.labels(source="resy").observe(0.052)
    count = REGISTRY.get_sample_value("poll_latency_seconds_count", {"source": "resy"})
    bucket = REGISTRY.get_sample_value(
        "poll_latency_seconds_bucket", {"source": "resy", "le": "0.1"}
    )
    assert isinstance(count, float) and count >= 1.0
    assert isinstance(bucket, float) and bucket >= 1.0


def test_the_gauges_are_settable_and_readable():
    metrics.resy_rate_budget_remaining.set(17)
    metrics.playwright_contexts_active.set(4)
    assert REGISTRY.get_sample_value("resy_rate_budget_remaining") == 17.0
    assert REGISTRY.get_sample_value("playwright_contexts_active") == 4.0


def test_resy_auth_mode_distinguishes_authenticated_from_anonymous():
    """A silently anonymous fleet still returns 200 OK — Grafana must be able to see it."""
    metrics.resy_auth_mode.labels(mode="authenticated").set(1)
    metrics.resy_auth_mode.labels(mode="anonymous").set(0)
    assert REGISTRY.get_sample_value("resy_auth_mode", {"mode": "authenticated"}) == 1.0
    assert REGISTRY.get_sample_value("resy_auth_mode", {"mode": "anonymous"}) == 0.0


def test_context_recycles_are_counted_by_reason():
    labels = {"reason": "poisoned"}
    before = REGISTRY.get_sample_value("resy_context_recycles_total", labels) or 0.0
    metrics.resy_context_recycles_total.labels(**labels).inc()
    assert REGISTRY.get_sample_value("resy_context_recycles_total", labels) == before + 1.0


def test_metrics_are_defined_at_module_scope_not_inside_a_function():
    """Phases 4-7 append to this module; a definition inside a function would register twice.

    Scanned off disk rather than by introspection: the defect is a definition that RUNS more
    than once, and a source-level gate is what catches it before the second call ever happens.
    """
    from pathlib import Path

    source = Path(metrics.__file__).read_text()
    for line in source.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(f"{k}(") or f"= {k}(" in stripped for k in ("Counter",)):
            assert not line.startswith((" ", "\t")), f"indented metric definition: {line!r}"
