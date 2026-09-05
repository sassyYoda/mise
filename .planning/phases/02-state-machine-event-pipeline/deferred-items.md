# Deferred Items — Phase 02

Out-of-scope discoveries logged during execution. Not fixed here (scope boundary rule).

| Found during | Item | Why deferred |
|---|---|---|
| 02-01 final state update | `gsd-tools query roadmap.update-plan-progress` reports `summary_count: 0` even though `02-01-SUMMARY.md` exists. Its `countMatchedSummaries` helper pairs a summary with a plan by full plan id, so `NN-NN-SUMMARY.md` never matches a slugged `NN-NN-slug-PLAN.md`. The per-plan checkbox marking works (it uses the short id), only the aggregate count is affected. | Pre-existing across the whole project — every Phase 01 plan hit it too (`01-0N-SUMMARY.md`, roadmap still shows one stale checkbox and no count). It is a GSD tooling issue, not project code, and renaming summaries would contradict each plan's explicit `<output>` directive. The `**Plans**: N/4` row is corrected by hand after each plan until the tool is fixed upstream. |
