# Deferred Items — Phase 02

Out-of-scope discoveries logged during execution. Not fixed here (scope boundary rule).

| Found during | Item | Why deferred |
|---|---|---|
| 02-01 final state update | `gsd-tools query roadmap.update-plan-progress` reports `summary_count: 0` even though `02-01-SUMMARY.md` exists. Its `countMatchedSummaries` helper pairs a summary with a plan by full plan id, so `NN-NN-SUMMARY.md` never matches a slugged `NN-NN-slug-PLAN.md`. The per-plan checkbox marking works (it uses the short id), only the aggregate count is affected. | Pre-existing across the whole project — every Phase 01 plan hit it too (`01-0N-SUMMARY.md`, roadmap still shows one stale checkbox and no count). It is a GSD tooling issue, not project code, and renaming summaries would contradict each plan's explicit `<output>` directive. The `**Plans**: N/4` row is corrected by hand after each plan until the tool is fixed upstream. |

## From plan 02-02

- **`services/poller/config.py` freezes env vars at import time.** `REDIS_URL`,
  `KAFKA_BOOTSTRAP_SERVERS` and `DATABASE_URL_ASYNC` are module-level `os.getenv(...)`
  constants, so any integration test module that transitively imports poller code during
  collection pins later tests to the localhost defaults. Worked around in
  `tests/integration/test_poller_expedite_release.py` with a `sys.modules` teardown.
  Out of scope for this plan (production code outside its file list, and the freeze is
  harmless in a real process where env is set before start). Consider converting the
  constants to functions when 02-03 adds `services/state_machine/main.py`.
