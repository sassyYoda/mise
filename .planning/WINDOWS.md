---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-09-05T08:42:00.000Z
---

# Broken Windows Ledger

> Cross-phase defect register. `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 3 | todo | services/poller/sources/resy/fixtures.py |  | Every Resy `/4/find` body is `[ASSUMED]` from two public captures (research A1/A2), not from the wire — each carries a `TODO(spike)` marker. `parse_resy` and every Resy test in the phase are built on this one shape. A human DevTools capture (docs/runbooks/resy-cookie-capture.md) must confirm it, and in particular whether `config.token` exists at all, before Resy polls production. | open |  | 2026-09-05T08:42:00.000Z |  |

````json
[
  {
    "id": 1,
    "kind": "todo",
    "phase": "3",
    "file": "services/poller/sources/resy/fixtures.py",
    "line": null,
    "description": "Every Resy /4/find body is [ASSUMED] from two public captures (research A1/A2), not from the wire — each carries a TODO(spike) marker. parse_resy and every Resy test in the phase are built on this one shape. A human DevTools capture (docs/runbooks/resy-cookie-capture.md) must confirm it, and in particular whether config.token exists at all, before Resy polls production.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-05T08:42:00.000Z",
    "resolved_at": null
  }
]
````
