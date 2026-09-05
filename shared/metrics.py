"""
The SINGLE definition site for every Prometheus metric in this repository (D-69).

Named symbols: scrape_ban_total, poll_latency_seconds, poll_total,
               resy_context_recycles_total, resy_rate_budget_remaining,
               playwright_contexts_active, resy_auth_mode,
               POLL_LATENCY_BUCKETS

================================ READ BEFORE EDITING ================================

**Every metric is defined ONCE, at module scope, against the default
`prometheus_client.REGISTRY`.** Phases 4-7 append to this file; they must never define a
metric of their own anywhere else, and they must never define one inside a function.

Why this is a hard rule and not a style preference: registering the same metric name twice
against a registry raises `ValueError: Duplicated timeseries in CollectorRegistry` at
**import time**, which takes the poller down at startup rather than at first scrape. Two
routes lead there, and this project has both:

* a definition inside a function, which re-registers on the second call; and
* a test fixture that evicts `shared.metrics` from `sys.modules`, or an `importlib.reload`.
  This repo already evicts modules in integration teardown (recorded in STATE.md for 02-02),
  so the second route is one careless fixture away. `tests/unit/test_metrics_registry.py`
  imports this module twice and asserts nothing raises.

**Sample-name gotcha (verified, research §Pitfall 6).** `Counter("scrape_ban_total", …)` is
stored internally as `scrape_ban` and emits the samples `scrape_ban_total` and
`scrape_ban_created`. A test must therefore read
`REGISTRY.get_sample_value("scrape_ban_total", labels)` — reading
`"scrape_ban_total_total"` returns `None`, and an `assert x is None` written against that
name passes forever while asserting nothing about the metric.

**Exposition.** The poller serves these on `METRICS_PORT` (default 9101) via
`prometheus_client.start_http_server(port, registry=REGISTRY)`, which returns
`(WSGIServer, Thread)` with `daemon=True`. That daemon thread is compatible with this
project's async-only rules — it introduces no `time.sleep(`, no `requests`, and no sync
`redis` import, so all three CI ban-greps stay green. Do not "fix" it into an async server.
Phase 7 scrapes the endpoint; nothing here writes to disk or to the network by itself.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# The library default tops out at 10.0 seconds. One Resy poll issues three Playwright
# requests through a browser context, and a slow one lands in `+Inf` — invisible to every
# latency percentile exactly when the fleet is degrading. These buckets extend to 60 s so a
# 30-second poll is a visible number rather than an overflow.
POLL_LATENCY_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


# -- Soft-ban detection (POLL-06, D-67) --
scrape_ban_total = Counter(
    "scrape_ban_total",
    "Soft bans detected by the response-signature canary, by source and verdict reason.",
    ["source", "reason"],
)

# -- Poll outcomes (POLL-02, POLL-04, D-69) --
poll_latency_seconds = Histogram(
    "poll_latency_seconds",
    "Wall time of one availability poll, from dispatch to parsed response.",
    ["source"],
    buckets=POLL_LATENCY_BUCKETS,
)

poll_total = Counter(
    "poll_total",
    "Polls completed, by source and terminal status (success | error | timeout | banned).",
    ["source", "status"],
)

# -- Playwright fleet health (POLL-04, D-60, D-67) --
resy_context_recycles_total = Counter(
    "resy_context_recycles_total",
    "BrowserContexts torn down and rebuilt, by reason (poisoned | age | error).",
    ["reason"],
)

playwright_contexts_active = Gauge(
    "playwright_contexts_active",
    "BrowserContexts currently alive in the pool. A drift below the configured size is a leak.",
)

# -- Rate budget (POLL-05, D-65) --
resy_rate_budget_remaining = Gauge(
    "resy_rate_budget_remaining",
    "Requests left in the current minute against RESY_GLOBAL_RPM, as last observed.",
)

# -- Authentication mode (research §Security Domain) --
# A fleet whose cookies failed to load still returns 200 OK with sanitised availability,
# which is indistinguishable from a soft ban at the response level. Exporting the mode is
# what lets Grafana tell "we are banned" from "we are anonymous" without a human guessing.
resy_auth_mode = Gauge(
    "resy_auth_mode",
    "1 for the auth mode the fleet is currently running in, 0 for the others.",
    ["mode"],
)
