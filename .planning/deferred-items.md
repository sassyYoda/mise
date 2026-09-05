# Deferred Items

Out-of-scope discoveries logged during execution. Each names what is wrong, why it was not
fixed in the plan that found it, and who should pick it up.

| Found in | Item | Why deferred |
|----------|------|--------------|
| 02-04 | `gsd-tools query roadmap.update-plan-progress` reports `summary_count: 0` for phase 2 even though all four `02-0N-SUMMARY.md` files exist, and rewrote the ROADMAP progress row from `3/4 In progress` to `0/4 Planned`. The row was corrected by hand in the `docs(02-04)` commit. The detector appears to expect `NN-MM-<slug>-SUMMARY.md` (matching the PLAN filenames) rather than the `NN-MM-SUMMARY.md` convention this project actually uses. | Tooling defect outside the repository under test; every future plan's state update will regress the same row until it is fixed or the naming convention changes. |
| 02-04 | `state.update-progress` reports `0/10` and renders `[░░░░░░░░░░] 0%` in STATE.md despite ten SUMMARY files on disk. Same detector, same cause. | Left untouched rather than hand-writing a global metric whose semantics are ambiguous while phase 1's own accounting is inconsistent (see next row). |
| 02-04 | Phase 1's ROADMAP plan checkboxes disagree with the phase directory: five of six plans are unchecked, but all six `01-0N-SUMMARY.md` files exist, while the progress table claims `5/6`. | Pre-existing, predates this phase, and phase 1 is separately blocked on human admin gates (Twilio 10DLC, DevTools spike, the 24 h PERF-02 run). Belongs to the phase 1 close-out, not to a phase 2 plan. |
| 02-04 | `services/state_machine/store.py` declares `MemoryStateStore` beside `RedisStateStore`, so importing the replay-only store pulls `redis.asyncio` into `scripts/replay_raw.py` transitively. No connection is opened and no production client is constructed. | Splitting `MemoryStateStore` into its own module would edit 02-03's file for a cosmetic gain. Revisit if a future consumer needs the pure store without the redis dependency at all. |
| 02-04 | `scripts/replay_raw.py` reads partition 0 only. `fetch_offset_range` already takes `partition` as a parameter, so exposing `--partition` is a one-line change. | `scripts/create_topics.py` creates every topic with `num_partitions=1` at MVP; the flag would be untestable dead surface until that changes. |
