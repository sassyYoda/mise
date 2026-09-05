---
phase: 06-pattern-intelligence-frontend-pwa
plan: 06
type: execute
wave: 6
depends_on: ["06-05"]
files_modified:
  - web/src/lib/feed.ts
  - web/src/lib/feed.test.ts
  - web/src/components/FeedRow.tsx
  - web/src/components/LiveFeed.tsx
  - web/src/components/LiveFeed.test.tsx
  - web/src/components/Search.tsx
  - web/src/components/Search.test.tsx
  - web/src/components/HowItWorks.tsx
  - web/src/components/StatsCounter.tsx
  - web/src/app/page.tsx
  - web/src/app/home.test.tsx
  - web/src/fixtures/sample-heatmap.json
  - web/src/test/fixtures/feed.ts
autonomous: true
requirements: [FE-02]

estimate:
  tokens: 92000
  raw_tokens: 92000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "FE-02 probe: the feed is server-rendered from the recent-events endpoint on first paint, then a client EventSource appends live events, keeping the latest five, releasing at most one event per second (D-112)."
    - "The reducer dedupes by event id: an event whose id has already been seen is dropped, and the seen-id list is bounded so a long-lived tab cannot grow without limit (D-112)."
    - "Feed overflow backstop: a 50-event burst delivered inside one second drains at one event per second, never drops the newest event, never renders more than five rows, and never floods the live region — verified by driving the reducer with fake timers (UI-SPEC UI Considerations, D-118)."
    - "The rate cap is enforced BEFORE the DOM append, not after — an uncapped live region during a burst of cancellations makes a screen reader unusable, which is why the cap is an accessibility mechanism as much as a rendering one (UI-SPEC Accessibility Contract)."
    - "The client never builds its own reconnect loop: the browser reconnects natively and sends the last-event-id header on its own, the server's retry frame (06-03) owns the backoff, and the error handler only sets a reconnecting flag after three consecutive errors (D-112a, RESEARCH Pitfall 4)."
    - "A 'Pause updates' toggle is present, at least 44 px, carries a pressed state, and while paused accumulates incoming events in the queue and reads back the pending count — WCAG 2.2.2 requires a pause mechanism for indefinitely auto-updating content (UI-SPEC A-6)."
    - "The feed list is a polite live region announcing additions only, the newest row carries the live dot, and the dot itself is decorative while the adjacent Live or Paused text is the accessible signal (UI-SPEC)."
    - "Feed populated state: exactly five rows are retained at steady state, newest first, oldest dropped, each row a fixed height so an append never shifts the section below (UI-SPEC UI Considerations)."
    - "Feed empty state renders the documented 'Quiet at the moment' copy and the container keeps its height so the page does not reflow when the first event arrives (UI-SPEC UI Considerations)."
    - "On an error the feed keeps its last-known rows and shows a reconnecting notice — it never blanks (UI-SPEC State Contracts)."
    - "Search empty state renders the documented 'No restaurants match that' copy while the input keeps its value and stays focused; skeleton rows appear only after the debounce, never on the first keystroke (UI-SPEC UI Considerations, State Contracts)."
    - "Search is keyboard navigable: arrow keys move through results, Enter activates, Escape closes, and each result links to the restaurant route (D-112)."
    - "The home sample heatmap is fed by a bundled JSON fixture rendered through the SAME `Heatmap` component with the sample flag set, so it carries the visible 'Sample data' badge and the accessible-name prefix (D-112, UI-SPEC pattern sentence rule 7)."
    - "The social-proof counter renders from the stats endpoint and is HIDDEN entirely when the value is unavailable or zero — it never renders a zero count (UI-SPEC State Contracts)."
    - "Section order on the home page is hero and search, then how-it-works, then the sample heatmap, then the counter, then the live feed — the feed is last so its live region and its updates are never above the fold and cannot influence LCP (D-112, UI-SPEC)."
    - "Above the fold there is exactly one image with the priority flag and no client-side data fetching except the search input; the hero headline is static text and is the only display-size type on the site (D-111, UI-SPEC Typography)."
  artifacts:
    - web/src/lib/feed.ts
    - web/src/components/FeedRow.tsx
    - web/src/components/LiveFeed.tsx
    - web/src/components/Search.tsx
    - web/src/components/HowItWorks.tsx
    - web/src/components/StatsCounter.tsx
    - web/src/app/page.tsx
    - web/src/fixtures/sample-heatmap.json
  key_links:
    - "`feedReducer` is pure and timer-free; the one-per-second cap is a timer in the `LiveFeed` island dispatching a tick action, which is what makes the cap testable with fake timers and no rendering."
    - "`LiveFeed` hydrates from the server-rendered recent-events list passed as a prop, so the feed is never blank on first paint and the client island owns only the append path."
    - "The sample heatmap reuses `Heatmap` and `bucket` from 06-05 — there is exactly one colour mapping in the app."
    - "Every fetch on this page goes through `src/lib/api.ts`; the EventSource is the single exception and is constructed from the same `API_BASE`."
  prohibitions:
    - "No client-side reconnect loop and no manual EventSource reconstruction inside the error handler."
    - "The EventSource is never constructed with credentials, so the feed stays a simple credential-free cross-origin GET."
    - "The sample heatmap never renders without its visible sample badge and its accessible-name prefix."
    - "The counter never renders a zero or a placeholder number."
    - "No data fetch runs above the fold other than the search input's own debounced query."
    - "The reducer never mutates its input state and never reads a clock."
  flagged_assumptions:
    - "UI-SPEC unresolved item (long-text / interactive-control): the 55-restaurant seed caps names at 20 characters, so the single-line ellipsis in `FeedRow` and in search results is untested against genuinely long names. Assumption carried: seed-bounded lengths are representative. A future non-seed restaurant with a 60-character name may truncate awkwardly in both places."
    - "RESEARCH A5: the exact JSON keys of the live feed payload are [ASSUMED] until Phase 5 has executed. The `FeedEvent` type and its mapping live only in `src/lib/api.ts` (06-04), so a shape difference is a one-file change — do not spread field names into components."
---

<objective>
Build the home page: a static hero with search, the how-it-works band, a labelled sample heatmap, a social-proof
counter, and the live activity feed with its rate cap, its pause control and its no-client-backoff discipline.

Purpose: FE-02 is the page most likely to be seen first and the one with the tightest LCP budget. Everything that
moves lives below the fold, and the one piece of genuinely live behaviour — the feed — is built on a pure reducer so
its hardest property (a burst that must not flood a live region) is testable without rendering anything.

Output: `src/lib/feed.ts`, five components, the assembled home route, a bundled sample fixture and four test modules.
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
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-05-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| route | `/` | server shell, two client islands below the fold |
| lib | `src/lib/feed.ts` | pure reducer: `feedReducer`, `MAX_SHOWN`, `FeedState`, `FeedAction` |
| component | `LiveFeed` | client island: EventSource, one-per-second tick, pause toggle, reconnecting notice |
| component | `FeedRow` | fixed-height row, live dot on the newest only |
| component | `Search` | client island: debounced query, keyboard navigation, skeletons after debounce |
| component | `HowItWorks` | three-step band on the sunken surface |
| component | `StatsCounter` | social-proof counter, hidden when unavailable |
| fixture | `src/fixtures/sample-heatmap.json` | bundled, realistic, always rendered with the sample flag |

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Tracer — the pure feed reducer, its rate cap and its burst backstop</name>
  <files>web/src/lib/feed.ts, web/src/lib/feed.test.ts, web/src/test/fixtures/feed.ts</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Architecture Patterns → Pattern 4 (the executed reducer, and why the cap is a timer outside it) and §Code Examples → "EventSource client island"
    - `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/web/src/lib/feed.ts` and `feed.test.ts` — executed green, 6/6 passing; copy the shape
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-112 (latest five, one per second, dedupe by event id)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §UI Considerations → the overflow row for the feed burst, and §Accessibility Contract → Live feed
    - `web/src/lib/api.ts` from 06-04 — the `FeedEvent` type this reducer is generic over
  </read_first>
  <behavior>
    - A received event whose id is already in the seen list leaves the state unchanged (referential equality is acceptable as the dedupe signal).
    - A received event is queued, not shown: the shown list only changes on a tick.
    - A tick with an empty queue leaves the state unchanged; a tick with a non-empty queue moves exactly one event from the queue to the front of the shown list.
    - The shown list is capped at five: the sixth tick drops the oldest.
    - The seen list is bounded to 200 ids so a long-lived tab cannot grow without limit.
    - Burst backstop: dispatching 50 distinct events and then advancing fake timers by 50 seconds yields exactly five shown rows, the newest of the 50 is among them, and no event was dropped before it reached the queue.
    - Burst backstop, second half: after 3 seconds of ticks exactly three events have moved to shown — the drain rate is exactly one per second and never bursts.
    - The reducer never mutates its input and never reads a clock.
  </behavior>
  <action>
Write `src/lib/feed.ts` as a pure reducer over a `FeedState` of `{ shown, queue, seen }` with a `received` action and
a `tick` action, and a `MAX_SHOWN` constant of five. The received action dedupes against the bounded seen list and
appends to the queue. The tick action shifts exactly one event from the queue to the front of the shown list and
slices the shown list to the cap. Keep the timer OUT of the reducer — that is what makes the one-per-second cap
testable with fake timers and no rendering, and it is the reason the burst backstop is a unit test rather than an
integration test. State that in the module docstring alongside D-112 and the UI-SPEC live-region rationale.

`src/test/fixtures/feed.ts`: a typed builder producing distinct feed events with sequential ids and known restaurant
names, including one with a name at the seed's longest length so the row-truncation path is exercised.

`src/lib/feed.test.ts`: assert every item in the behavior block using the fake-timer pattern from the research
scaffold. The 50-event burst test is the UI-SPEC overflow backstop and must assert all three of its properties —
five rows, the newest present, and one-per-second drain.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/lib/feed.test.ts` exits 0.
    - The burst test asserts exactly 5 shown rows after 50 events and 50 seconds of ticks, and asserts the newest event id is present.
    - `grep -c 'setInterval\|setTimeout' web/src/lib/feed.ts` equals 0 (no timer in the reducer).
    - `grep -cE 'Date\.now|new Date\(' web/src/lib/feed.ts` equals 0 (no clock in the reducer).
    - `cd web && npm run typecheck && npm run lint` exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/lib/feed.test.ts</automated>
  </verify>
  <done>The feed's hardest property — a burst that must not flood the live region — is proven in a pure unit test before any component exists.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The live feed island, its row, and the search island</name>
  <files>web/src/components/FeedRow.tsx, web/src/components/LiveFeed.tsx, web/src/components/LiveFeed.test.tsx, web/src/components/Search.tsx, web/src/components/Search.test.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Component Inventory item 7 (FeedRow geometry, truncation, enter animation), §Accessibility Contract → Live feed (the live region attributes, the pause toggle, the decorative dot), §State Contracts (the live feed and search rows), §Copywriting Contract → Buttons (the pause and resume labels) and → Empty states (search and feed rows) and → "Live feed row format" and → "Error and offline states" (the reconnecting notice)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-112 (search behaviour, feed behaviour), D-112a (server-side backoff, reconnecting after three errors)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Common Pitfalls → Pitfall 4 (the error handler that must do nothing) and §Code Examples → "EventSource client island"
    - `web/src/lib/feed.ts` from Task 1, `web/src/lib/format.ts` and `web/src/components/ui/*` from 06-04
    - `docs/api.md` feed and restaurant-search sections as written in 06-03
  </read_first>
  <behavior>
    - `FeedRow` renders the documented row format, gives the newest row the live dot and every other row none, keeps a fixed height, and puts the full restaurant name in a title attribute when the visible name is truncated.
    - `LiveFeed` renders its server-provided initial rows immediately, before any client effect runs.
    - `LiveFeed` opens exactly one EventSource for the lifetime of the component and closes it on unmount; the error handler creates no new connection.
    - After three consecutive error events the reconnecting notice appears; a subsequent open event restores the Live label.
    - The pause toggle carries a pressed state; while paused no queued event moves to shown and the toggle's label reports the pending count; resuming drains at the same one-per-second rate.
    - The list is a polite live region announcing additions only, and the dot is hidden from assistive technology.
    - With zero rows the documented feed empty copy renders and the container keeps its height.
    - `Search` issues exactly one request per typing burst (debounced), shows skeleton rows only after the debounce elapses and never on the first keystroke, keeps the input's value and focus when there are no matches, renders the documented no-match copy, and supports arrow-key navigation with Enter to activate and Escape to close.
    - Both islands produce zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
`src/components/FeedRow.tsx`: a presentational row to the UI-SPEC geometry — a live-dot column occupied only on the
newest row, the formatted text from `src/lib/format.ts`, and a timestamp. Rows are list items inside one ordered
list; the height is fixed so an append cannot shift the section below. Apply the enter transition from the motion
tokens and let the global reduced-motion block suppress it — do not branch on a media query in JavaScript.

`src/components/LiveFeed.tsx`: the client island. It receives the server-hydrated rows as a prop and seeds the
reducer with them, so first paint is never blank. In one effect it constructs a single EventSource against the feed
path on `API_BASE` without credentials, subscribes to the slot-opened event name, dispatches a received action per
message, sets a live status on open, and — in the error handler — increments a counter and sets the reconnecting
status once it reaches three, and does nothing else. Add the comment recording why: the browser reconnects on its own
and fires an error on every reconnect (measured at eight in three seconds), the server's retry frame owns the
backoff, and constructing a new EventSource here multiplies connections within seconds. A second effect runs the
one-second tick interval; both are torn down on unmount.

Render the region header with the status label (Live, Paused or Reconnecting), the decorative dot, and the pause
toggle at 44 px with a pressed state whose label reports the pending count while paused. Render the list as a polite
live region announcing additions only. Render the documented empty copy when there are no rows, keeping the
container's height.

`src/components/Search.tsx`: the client island for the hero. A labelled text input (a placeholder is not a label),
a debounce before issuing the query through `src/lib/api.ts`, skeleton rows shown only after the debounce elapses, a
results list with arrow-key navigation, Enter activation and Escape dismissal, each result an anchor to the
restaurant route showing the name and the meta line. On no matches render the documented copy while keeping the
input's value and focus. On a failed query render the inline error with a retry affordance and keep any existing
results.

Both test modules drive their behavior blocks with fake timers and a stubbed global fetch or a stubbed EventSource
class — there is no mock-service-worker package in this project. Assert the single-connection property by counting
constructions of the stubbed EventSource across a sequence of error events. Run axe over each rendered island.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/components/LiveFeed.test.tsx src/components/Search.test.tsx` exits 0.
    - The LiveFeed test asserts the stubbed EventSource constructor was called exactly once across three dispatched error events.
    - `grep -c 'new EventSource' web/src/components/LiveFeed.tsx` equals 1.
    - `grep -c 'withCredentials' web/src/components/LiveFeed.tsx` equals 0.
    - `grep -c 'aria-pressed' web/src/components/LiveFeed.tsx` is at least 1 and `grep -c 'aria-live' web/src/components/LiveFeed.tsx` is at least 1.
    - `cd web && npm run typecheck && npm run lint && npm run build` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/components/LiveFeed.test.tsx src/components/Search.test.tsx</automated>
  </verify>
  <done>One EventSource per tab, a pause control that satisfies the auto-updating-content rule, a feed that never blanks, and a search that never fires on the first keystroke.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The assembled home page — hero, how-it-works, labelled sample heatmap, counter</name>
  <files>web/src/components/HowItWorks.tsx, web/src/components/StatsCounter.tsx, web/src/app/page.tsx, web/src/app/home.test.tsx, web/src/fixtures/sample-heatmap.json</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Page Layout Contracts (the `/` row, the section order and the above-the-fold contract), §Typography (the display role is the home hero headline only), §Component Inventory item 4 (the accent-outline badge is used only for the sample-data label), §State Contracts (the social-proof counter row), §Copywriting Contract → Buttons (the hero label)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-112 (the full home contract), D-111 (the LCP budget: static hero text plus one priority image, no above-the-fold data fetching), CONTEXT specific ideas (the sample heatmap must be unmistakably sample)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Lighthouse gate — the ~700 ms of LCP headroom the scaffold leaves, and why the budget is a real constraint on this page
    - `web/src/components/Heatmap.tsx` from 06-05 — the `sample` prop
    - `web/src/components/{LiveFeed,Search}.tsx` from Task 2 and `web/src/lib/api.ts` from 06-04
  </read_first>
  <behavior>
    - The page renders its sections in the documented order: hero with search, how-it-works, sample heatmap, counter, live feed.
    - Exactly one h1 exists and it is the hero headline; it is the only element using the display type size.
    - Exactly one image carries the priority flag and it is above the fold.
    - The sample heatmap renders through the shared component with the sample flag set, and its rendered output contains both the visible sample badge text and the sample prefix on the container's accessible name.
    - The counter renders the value from the stats endpoint with tabular figures and singular or plural wording that is correct at 1 and at 2; when the stats fetch returns null the counter element is absent from the DOM entirely.
    - When the recent-events fetch returns null the feed renders its empty state rather than crashing, and the rest of the page still renders.
    - When every fetch returns null the page renders the documented backend-unreachable copy and still builds — this is the state a Vercel deploy without a backend shows.
    - The assembled page produces zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
`src/fixtures/sample-heatmap.json`: a bundled, realistic 7x24 payload in the exact D-107 shape with a plausible
`max`, a mixture of sparse and dense cells and an evening-heavy distribution. It is data, not a screenshot, and it is
rendered through the same component the live page uses so the two can never drift.

`src/components/HowItWorks.tsx`: the three-step band on the sunken surface with sentence-case headings and body copy
in the project's voice — warm, concise, second person, no exclamation marks and no emoji.

`src/components/StatsCounter.tsx`: renders the social-proof value with tabular figures and correct singular and
plural wording. When the value is unavailable or zero it renders nothing at all — a zero count is worse than no
count.

`src/app/page.tsx`: the server shell. Above the fold: the display-size headline as the single h1, a body subhead, the
hero primary call to action, the search island, and one image with the priority flag. Below the fold, in order: the
how-it-works band, the sample heatmap card rendered with the sample flag set, the counter, and the live feed
hydrated from a server-side recent-events read. Every read goes through `src/lib/api.ts`; a null result selects the
documented empty or offline rendering for that surface only. Do not fetch anything above the fold other than through
the search island's own input.

`src/app/home.test.tsx`: assert every item in the behavior block with a stubbed global fetch over the typed fixtures,
including the all-null case, the counter-hidden case, and the sample-label assertions. Run axe over the assembled
output.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/app/home.test.tsx` exits 0.
    - The home test asserts the rendered output contains the sample badge text AND that the heatmap container's accessible name begins with the sample prefix.
    - `grep -c 'priority' web/src/app/page.tsx` equals 1.
    - `cd web && npm test` exits 0 (the whole frontend suite).
    - `make web-build-offline` exits 0 with the finished home page in place.
    - `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test && make -C ../ web-build-offline</automated>
  </verify>
  <done>The home page renders its five sections in order, labels its sample data unmistakably, hides rather than fakes an unavailable counter, and still builds green with no backend.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| SSE stream → live region | server-pushed events are announced to assistive technology as they arrive |
| search input → API query | user text is sent to a public search endpoint |
| bundled fixture → rendered page | sample data sits next to live data on the same page |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-27 | Denial of service | SSE connection multiplication from a buggy client | high | mitigate | Exactly one EventSource per island, never reconstructed in the error handler, asserted by a constructor-count test; the server's retry frame (06-03) paces reconnects |
| T-06-28 | Denial of service | live-region flooding during a cancellation burst | high | mitigate | The one-per-second cap is applied before the DOM append and proven by a 50-event burst test; the pause toggle lets a user stop updates entirely |
| T-06-29 | Tampering | sample data mistaken for live data | high | mitigate | The sample heatmap always renders with the sample flag, producing a visible badge and an accessible-name prefix, asserted in the home test |
| T-06-30 | Tampering | XSS via a restaurant name in a feed row or search result | high | mitigate | All strings render as text nodes; the raw-HTML-prop gate from 06-04 covers the tree |
| T-06-31 | Information disclosure | credentials attached to a cross-origin stream | medium | mitigate | The EventSource is constructed without credentials, keeping the feed a simple credential-free cross-origin GET; a grep asserts it |
| T-06-32 | Denial of service | a request per keystroke against the search endpoint | medium | mitigate | The input debounces and issues one request per burst, asserted by a fake-timer test |
| T-06-SC | Tampering | npm installs | high | mitigate | This plan installs nothing. Recorded in the SUMMARY |
</threat_model>

<verification>
- `cd web && npm test && npm run typecheck && npm run lint && npm run build`
- `make web-build-offline`
</verification>

<success_criteria>
- The feed reducer's burst backstop is green: 50 events in, five rows out, one per second, newest retained.
- Exactly one EventSource per tab across repeated error events; no client-side reconnect loop exists.
- A pause toggle is present, pressed-state aware, and reports its pending count.
- The sample heatmap is unmistakably labelled in both the visual and the accessible output.
- The home page builds and renders with every fetch returning null.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-06-SUMMARY.md` when done.
Record the actual live-feed payload field names taken from the Phase 5 snapshot, and note any place the assumed
`FeedEvent` shape had to change so a reviewer can confirm the change stayed inside `src/lib/api.ts`.
</output>
