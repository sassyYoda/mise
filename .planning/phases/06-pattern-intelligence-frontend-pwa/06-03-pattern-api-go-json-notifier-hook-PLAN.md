---
phase: 06-pattern-intelligence-frontend-pwa
plan: 03
type: execute
wave: 3
depends_on: ["06-02"]
files_modified:
  - services/api/routers/restaurants.py
  - services/api/routers/links.py
  - services/api/sse.py
  - services/notifier/pattern_hook.py
  - docs/api.md
  - tests/unit/test_pattern_hook.py
  - tests/unit/test_sse_retry_frame.py
  - tests/unit/test_templates.py
  - tests/integration/test_pattern_routes.py
  - tests/integration/test_go_json_mode.py
autonomous: true
requirements: [PATTERN-02, PATTERN-03, FE-06]

estimate:
  tokens: 84000
  raw_tokens: 84000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`GET /api/restaurants/{slug}/heatmap` returns the D-107 payload verbatim — `{days: 7, hours: 24, cells, observations_threshold: 10, window_days: 30, max}` — with 168 cells for every restaurant, including one with zero events (D-108)."
    - "`GET /api/restaurants/{slug}/pattern` returns the `PatternReport` shape including `status`, `days_of_history`, `n_events`, `window_days`, `rules` (each with `n`, `ci_low`, `ci_high`) and `summary_text` (D-108)."
    - "`GET /api/restaurants/{slug}` embeds `pattern_status` read from the SAME cached `get_pattern(slug)` value the `/pattern` route returns, so the detail page can render the placeholder without a second request and the two can never disagree (D-108, RESEARCH Pitfall 8)."
    - "Both new routes are added to the EXISTING Phase 5 restaurants router — no new router module is created (D-108)."
    - "PATTERN-03 empty probe: `estimate_window_text(source, restaurant_id)` returns `None` when the pattern status is not `ready`, when the duration sample size is below 10, and when the restaurant has no events at all — it never raises and never returns an empty string (D-108)."
    - "PATTERN-03 encoding probe: when a sentence IS returned it is the exact form `estimated window: ~{median_minutes} minutes based on this restaurant's history`, `median_minutes` is a whole number, and every character is ASCII so the SMS GSM-7 budget from Phase 4 D-81a is unaffected."
    - "`services/notifier/templates.py` renders the estimated-window line when the hook returns a string and omits the line entirely when it returns `None` — proven by extending the Phase 4 template test (PATTERN-03, ROADMAP SC3)."
    - "FE-06: `GET /go/{token}` with `Accept: application/json` returns `{available, redirect_url, restaurant, slot, checked_at}` and still performs the Phase 4 D-84 click capture (`notification_log.clicked_at`) and the `slot_still_available` write on that same request."
    - "`GET /go/{token}` without a JSON `Accept` header keeps its Phase 4 behaviour byte-for-byte: a 302 to the platform URL when available, the plain 'gone' response otherwise — SMS-opened links landing on the API host are unaffected (D-116)."
    - "The SSE stream's FIRST frame is `retry: 2000` so reconnect backoff is server-driven and the browser needs no client-side reconnect loop (D-112a). If Phase 5 already emits a `retry:` frame this is a verification-only change and the value is left as Phase 5 set it."
    - "`docs/api.md` documents the two new restaurant sub-routes, the `/go` JSON mode and the `pattern_status` field with curl examples, so the Phase 6 frontend api client is written against a real snapshot rather than an assumption."
  artifacts:
    - services/notifier/pattern_hook.py
    - tests/unit/test_pattern_hook.py
    - tests/unit/test_sse_retry_frame.py
    - tests/integration/test_pattern_routes.py
    - tests/integration/test_go_json_mode.py
    - docs/api.md
  key_links:
    - "`services/api/routers/restaurants.py` calls `shared.pattern.service.get_heatmap` / `get_pattern` / `pattern_status` — the route contains no SQL and no threshold of its own."
    - "`services/notifier/pattern_hook.py` calls `shared.pattern.service.get_pattern` and reads `report.duration.p50` plus `report.duration.n`; the Phase 4 `templates.py` contract (`str | None`, line omitted on `None`) is unchanged."
    - "`GET /go/{token}` JSON mode's `redirect_url` comes from the API's own `shared/links.py` builder — never from a query parameter — which is what makes the 06-08 frontend origin allowlist a defence in depth rather than the only defence."
    - "`docs/api.md` is the contract plan 06-04's `src/lib/api.ts` is typed against."
  prohibitions:
    - "No new FastAPI router module is created for the pattern routes; they are added to the Phase 5 restaurants router."
    - "The pattern routes never recompute a threshold: `observations_threshold`, `PATTERN_MIN_EVENTS` and the 14-day gate exist only in `shared/pattern/`."
    - "`estimate_window_text` never returns a string when the duration sample size is below 10, and never returns an empty or whitespace-only string."
    - "The `/go` JSON branch never changes the status code, redirect target or click-capture behaviour of the existing non-JSON path."
    - "No `str(exc)` in any log call added by this plan; `safe_error(exc)` only."
    - "No management token, `/go` token or booking token is written into any log line or into any response body added by this plan."
---

<objective>
Expose the pattern intelligence on the Phase 5 API, wire it into the Phase 4 notifier, and add the two small
API-side affordances the frontend needs: `/go` JSON mode and a server-driven SSE `retry:` frame.

Purpose: this is the seam between the backend half and the frontend half of Phase 6. After this plan, `docs/api.md`
is a complete contract and every remaining plan is frontend work against a real snapshot.

Output: two new sub-routes on the existing restaurants router, an implemented `pattern_hook`, a JSON branch on
`/go/{token}`, a `retry:` first frame on the feed stream, and updated `docs/api.md`.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-02-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| route | `GET /api/restaurants/{slug}/heatmap` | added to the Phase 5 restaurants router |
| route | `GET /api/restaurants/{slug}/pattern` | added to the Phase 5 restaurants router |
| response field | `pattern_status` on `GET /api/restaurants/{slug}` | `collecting_data` \| `ready` |
| route behaviour | `GET /go/{token}` with `Accept: application/json` | `{available, redirect_url, restaurant, slot, checked_at}` |
| stream frame | `retry: 2000` as the first frame of `GET /api/feed/live` | server-driven reconnect backoff |
| lib function | `services.notifier.pattern_hook.estimate_window_text(source, restaurant_id) -> str \| None` | implemented |
| docs | `docs/api.md` sections for both new routes, the JSON mode and `pattern_status` | frontend contract |

<tasks>

<task type="tracer">
  <name>Task 1: Tracer — heatmap and pattern routes end to end from a seeded database to JSON</name>
  <files>services/api/routers/restaurants.py, tests/integration/test_pattern_routes.py, docs/api.md</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-107 (heatmap payload shape) and D-108 (both route paths, `pattern_status` embedding)
    - `services/api/routers/restaurants.py` as Phase 5 shipped it — the existing router prefix, dependency wiring, response models and the merged-restaurant shape from D-100
    - `services/api/app.py` — how routers are mounted, and the lifespan-provided DB/Redis resources
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Common Pitfalls → Pitfall 8 (why `pattern_status` must come from the same cached value)
    - `shared/pattern/service.py` as written in 06-02 — `get_pattern`, `get_heatmap`, `pattern_status`, the not-found path
    - `tests/integration/conftest.py` — `db_urls`, `redis_url`, `apply_migrations`, and the Phase 5 route-client idiom
    - `docs/api.md` as Phase 5 shipped it — the section shape and curl-example style to match
  </read_first>
  <action>
Add exactly two route handlers to the EXISTING Phase 5 restaurants router (do not create a new module): a
`GET /{slug}/heatmap` and a `GET /{slug}/pattern` under whatever prefix the Phase 5 router already declares so the
public paths are `/api/restaurants/{slug}/heatmap` and `/api/restaurants/{slug}/pattern`. Each handler resolves the
slug through `shared.pattern.service`, returns the payload as-is, and maps the service's not-found path to a 404 with
the router's existing error shape. Declare pydantic response models mirroring the D-107 heatmap payload and the
`PatternReport` fields so the OpenAPI snapshot Phase 5 pins carries them.

Extend the existing `GET /api/restaurants/{slug}` handler with a `pattern_status` field sourced from
`shared.pattern.service.pattern_status(slug)` — the accessor over the SAME cached `get_pattern` value. Add an inline
comment stating that recomputing the gate here would let the detail page and the `/pattern` route disagree at the
14-day boundary and render an empty card (Pitfall 8).

Neither handler contains SQL, a threshold literal, or a `sparse` computation — all three live in `shared/pattern/`.

`tests/integration/test_pattern_routes.py` (`pytestmark = pytest.mark.integration`): seed `restaurants` rows and a
deterministic `availability_events` corpus, refresh the continuous aggregate on an AUTOCOMMIT connection, and assert
through the API client that: `/heatmap` returns exactly 7 rows of 24 cells with the documented `observations_threshold`
and `window_days`; a cell with fewer than 10 observations is flagged `sparse` and one with 10 or more is not; a
restaurant with zero events returns 168 cells all `sparse` with `max` 0 (the PATTERN-02 empty probe);
`/pattern` for a below-threshold restaurant returns `status` `collecting_data` with the quantified placeholder and an
empty rule list; `/pattern` for an above-threshold restaurant returns at least one rule and every rule carries `n`,
`ci_low` and `ci_high`; `GET /api/restaurants/{slug}` returns a `pattern_status` equal to the `/pattern` route's
`status` in the same test run; an unknown slug returns 404 on all three.

Update `docs/api.md` with a section per new route in the existing style, including a curl example and a trimmed
example response body, and document the new `pattern_status` field on the restaurant detail response. This document
is the contract plan 06-04 types `src/lib/api.ts` against.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_pattern_routes.py -x -q -p no:cacheprovider` exits 0.
    - `grep -c 'restaurants/{slug}/heatmap' docs/api.md` is at least 1 and `grep -c 'restaurants/{slug}/pattern' docs/api.md` is at least 1.
    - `grep -c 'pattern_status' docs/api.md` is at least 1.
    - `ls services/api/routers/ | grep -c '^pattern' ` equals 0 (no new router module was created).
    - `grep -v '^\s*#' services/api/routers/restaurants.py | grep -cE '\b(10|30|14)\b\s*#?.*(threshold|min_events|days_of_history)'` equals 0 (no threshold literal leaked into the route).
    - `uv run pytest tests/unit -x -q -W error::RuntimeWarning` exits 0 and the Phase 5 OpenAPI snapshot test passes with the two new routes recorded.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/integration/test_pattern_routes.py -x -q -p no:cacheprovider</automated>
  </verify>
  <done>A seeded restaurant's heatmap and pattern are served as JSON over HTTP, `pattern_status` agrees with `/pattern` in the same run, and `docs/api.md` records the contract.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: PATTERN-03 — implement the notifier's estimated-window hook</name>
  <files>services/notifier/pattern_hook.py, tests/unit/test_pattern_hook.py, tests/unit/test_templates.py</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-108 (the hook's exact return contract and gate)
    - `.planning/phases/04-notification-pipeline/04-CONTEXT.md` — D-81 (`templates.py`, the stub returning `None`, "templates omit the line when `None`") and D-81a (the SMS GSM-7 septet budget)
    - `services/notifier/pattern_hook.py` as Phase 4 shipped it — the existing signature and docstring
    - `services/notifier/templates.py` — where the estimated-window line is interpolated and how the omission is expressed
    - `tests/unit/test_templates.py` — the existing Phase 4 test module this plan extends
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Copywriting Contract → pattern sentence rule 6 (the exact sentence the frontend also renders)
    - `services/state_machine/persistence.py` (lines 105-125) — the `safe_error` logging idiom
    - `shared/pattern/service.py` — `get_pattern` and the `DurationSummary` shape
  </read_first>
  <behavior>
    - With a pattern whose `status` is `ready` and whose duration sample size is 15 and median 480 seconds, the hook returns exactly `estimated window: ~8 minutes based on this restaurant's history`.
    - With `status` `ready` but a duration sample size of 9, the hook returns `None`.
    - With `status` `collecting_data` and a duration sample size of 40, the hook returns `None`.
    - With a restaurant that has no events at all, the hook returns `None` and does not raise.
    - When the pattern service raises (database or Redis unavailable), the hook logs with `safe_error` and returns `None` — a notification is never blocked by the pattern path.
    - The returned string is pure ASCII and contains no em dash, so the Phase 4 GSM-7 septet budget is unchanged.
    - `templates.py` renders a message containing the sentence when the hook returns a string and a message containing no estimated-window line at all when it returns `None`.
  </behavior>
  <action>
Implement `services/notifier/pattern_hook.py :: estimate_window_text(source, restaurant_id) -> str | None`, replacing
the Phase 4 stub body while keeping its signature and its call sites untouched. Update the module docstring to cite
PATTERN-03, D-108 and ROADMAP SC3, and to end with a `Named symbols:` line.

Resolve the `(source, restaurant_id)` platform pair to a slug and call `shared.pattern.service.get_pattern(slug)`.
Return a sentence ONLY when the report's `status` is `ready` AND its `duration` is present AND `duration.n` is at or
above the duration threshold from `PatternConfig`. Convert `duration.p50` from seconds to whole minutes with
`round()` and render the sentence in the exact D-108 form. In every other case return `None` — do not return an empty
string, because the Phase 4 template omits the line on `None` and would render a blank line on `""`.

Wrap the whole body in a try/except that logs with `safe_error(exc)` and returns `None`: a pattern lookup failure
must degrade the notification's richness, never its delivery. Note that reason in a comment.

Add a threshold guard comment stating that the number is read from `PatternConfig`, not written here.

`tests/unit/test_pattern_hook.py`: drive every case in the `<behavior>` block with the pattern service stubbed
(monkeypatch `shared.pattern.service.get_pattern` — no database in a unit test), including the raising case. Assert
the returned sentence with an exact string equality and assert it encodes cleanly to ASCII.

Extend `tests/unit/test_templates.py` with two cases in the Phase 4 module's existing style: the hook returning a
string produces a message containing that sentence in the email body, the SMS body and the push body per whichever
channels Phase 4 wired it into; the hook returning `None` produces messages containing no estimated-window text and
no blank artefact where the line would have been.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_pattern_hook.py -x -q` exits 0.
    - `uv run pytest tests/unit/test_templates.py -x -q` exits 0.
    - `uv run python -c "import inspect, services.notifier.pattern_hook as m; s=inspect.getsource(m); assert 'safe_error' in s and 'str(exc)' not in s"` exits 0.
    - `grep -v '^\s*#' services/notifier/pattern_hook.py | grep -c "return \"\""` equals 0.
    - `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_pattern_hook.py tests/unit/test_templates.py -x -q</automated>
  </verify>
  <done>Notifications carry an estimated availability window when the data supports it and carry nothing at all when it does not, with the exact sentence pinned by an equality assertion.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: `/go` JSON mode and the server-driven SSE retry frame</name>
  <files>services/api/routers/links.py, services/api/sse.py, tests/integration/test_go_json_mode.py, tests/unit/test_sse_retry_frame.py, docs/api.md</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-116 (the JSON mode contract and the preserved 302), D-116a (the page fetches server-side, so no CORS preflight is involved), D-112a (server-side `retry:`)
    - `.planning/phases/04-notification-pipeline/04-CONTEXT.md` — D-84 (`/go/{token}` verify, `clicked_at` write, `slot_still_available` computation, 302 vs "gone" response), D-86a (`slot_still_available` NULL when the Phase 2 slot record has expired)
    - `services/api/routers/links.py` as Phase 4 shipped it — the existing handler, the token verifier and the exact 302 path
    - `services/api/sse.py` as Phase 5 shipped it — `FeedHub`, the stream generator, and whether a `retry:` frame is already emitted
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md` → "`services/api/routers/restaurants.py`, `links.py`, `services/api/sse.py`" — the executed SSE frame ordering from the research proof
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Common Pitfalls → Pitfall 4 (why the backoff belongs on the server)
    - `shared/links.py` — `platform_booking_url`, the only source of `redirect_url`
  </read_first>
  <behavior>
    - `GET /go/{token}` with `Accept: application/json` and a still-available slot returns 200 with a JSON body carrying `available` true, a `redirect_url` produced by `shared/links.py`, a `restaurant` object (at minimum name and slug), a `slot` object (date, time, party size) and a `checked_at` timestamp.
    - The same request with a slot that is gone returns 200 with `available` false and a `redirect_url` that is still present so the page can offer a manual link, plus the same restaurant and slot detail.
    - Either JSON request writes `notification_log.clicked_at` and persists `slot_still_available` exactly as the Phase 4 non-JSON path does — verified by reading the row back.
    - `GET /go/{token}` without a JSON `Accept` header still returns the Phase 4 302 (available) or the Phase 4 "gone" response (unavailable), unchanged.
    - An invalid or unknown token returns the Phase 4 error behaviour in both modes and writes nothing.
    - The first bytes written to a `GET /api/feed/live` connection are a `retry:` frame, before any `id:`/`event:`/`data:` frame and before the first `: ping` comment.
  </behavior>
  <action>
Branch the EXISTING `/go/{token}` handler on the request's `Accept` header rather than adding a second route: when
the header names `application/json`, serialise the outcome; otherwise fall through to the untouched Phase 4 code
path. Perform the token verification, the `clicked_at` write and the `slot_still_available` computation BEFORE the
branch so both modes share one implementation and the click capture cannot drift between them (Phase 4 D-84). Declare
a pydantic response model for the JSON body with the five D-116 fields so it lands in the OpenAPI snapshot.

`redirect_url` is always taken from `shared/links.py :: platform_booking_url` — never echoed from a query parameter.
Add a comment saying so: it is the reason the frontend's origin check in plan 06-08 is defence in depth rather than
the only defence against an open redirect.

In `services/api/sse.py`, make the stream generator's first yielded frame `retry: 2000` followed by a blank line,
before any replay of the ring buffer and before the first heartbeat. If Phase 5 already emits a `retry:` frame,
change nothing and convert this into a verification-only step, recording in the SUMMARY which case applied and what
value Phase 5 chose. Add a comment citing D-112a and RESEARCH Pitfall 4: the browser reconnects on its own and fires
`error` on every reconnect, so the backoff belongs here and the client must never build its own reconnect loop.

`tests/unit/test_sse_retry_frame.py`: drive the stream generator directly (no server) and assert the first yielded
chunk starts with the retry frame and that it precedes any `id:` frame — a byte-level assertion, in the style of the
Phase 5 SSE framing unit tests.

`tests/integration/test_go_json_mode.py` (`pytestmark = pytest.mark.integration`): seed a notification log row and a
Phase 2 slot record, then exercise every case in the `<behavior>` block, reading `notification_log` back to prove the
click capture in JSON mode. Assert the non-JSON path's status code and `Location` header are byte-identical to the
Phase 4 expectation so the SMS-opened-link behaviour is provably unchanged.

Document the JSON mode in `docs/api.md`: the `Accept` header that triggers it, the response body, and an explicit
note that the 302 behaviour is retained for non-JSON clients.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_go_json_mode.py -x -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/unit/test_sse_retry_frame.py -x -q` exits 0.
    - `grep -c 'application/json' docs/api.md` is at least 1 and the `/go` section documents both modes.
    - `ls services/api/routers/ | wc -l` is unchanged from before this task (no new router file).
    - `uv run pytest tests/unit -x -q -W error::RuntimeWarning` and `uv run pytest tests/integration -q -p no:cacheprovider` both exit 0.
    - `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_sse_retry_frame.py tests/integration/test_go_json_mode.py -x -q -p no:cacheprovider</automated>
  </verify>
  <done>The alert-landing page can fetch a typed JSON verdict server-side while SMS-opened links still redirect, and the feed stream tells the browser how long to wait before reconnecting.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| public internet → `/api/restaurants/{slug}/*` | unauthenticated GETs with a user-supplied slug |
| notification link → `/go/{token}` | a capability token arriving from an email, SMS or push click |
| Kafka events → SSE subscribers | events multicast to unauthenticated cross-origin readers |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-10 | Tampering | open redirect on `/go/{token}` | critical | mitigate | `redirect_url` is built by `shared/links.py` from the token's own claims; no query parameter reaches it. The integration test asserts the returned host is an OpenTable or Resy host |
| T-06-11 | Information disclosure | `/go` token in logs | high | mitigate | Phase 5 D-97 logs the path template with the token replaced; this plan adds no log line carrying the raw path, and the JSON body echoes no token |
| T-06-12 | Spoofing | forged `/go` token | high | mitigate | Unchanged Phase 4 HMAC verification runs before the `Accept` branch, so JSON mode inherits it exactly |
| T-06-13 | Information disclosure | pattern routes leaking non-public data | medium | mitigate | Both routes return only aggregate counts and rendered prose from `shared/pattern/`; no watch, user, email or booking token is reachable from the payload |
| T-06-14 | Denial of service | unauthenticated pattern route hammering | medium | mitigate | Both routes are served from the 600 s Redis cache built in 06-02; the CAGG bounds the cold path. Phase 5's per-IP limiting covers write routes; read amplification is bounded by the cache |
| T-06-15 | Denial of service | SSE connection multiplication | medium | mitigate | The server-side `retry: 2000` frame paces reconnects; RESEARCH Pitfall 4 shows a client-side loop is what multiplies connections, and plan 06-06 forbids one |
| T-06-SC | Tampering | python package installs | high | mitigate | This plan adds no dependency. Recorded in the SUMMARY |
</threat_model>

<verification>
- `uv run pytest tests/unit -x -q -W error::RuntimeWarning`
- `uv run pytest tests/integration -q -p no:cacheprovider`
- `uv run ruff check . && uv run mypy shared/ services/ scripts/`
- The Phase 5 OpenAPI snapshot test is green with the two new routes and the JSON response model recorded
</verification>

<success_criteria>
- `/heatmap` and `/pattern` are live on the existing restaurants router and documented in `docs/api.md`.
- `pattern_status` on the restaurant detail response is read from the same cached value as `/pattern`.
- `estimate_window_text` returns the exact sentence when and only when the data supports it, and `templates.py` omits the line otherwise.
- `/go/{token}` serves JSON to the frontend and a 302 to everyone else, with identical click capture.
- The feed stream's first frame is a `retry:` frame.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-03-SUMMARY.md` when done.
Record whether the SSE `retry:` frame was added or already present (and its value), and paste the exact
`docs/api.md` route list the frontend api client must be typed against.
</output>
