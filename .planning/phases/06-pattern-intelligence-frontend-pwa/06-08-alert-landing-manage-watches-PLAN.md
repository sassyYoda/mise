---
phase: 06-pattern-intelligence-frontend-pwa
plan: 08
type: execute
wave: 8
depends_on: ["06-07"]
files_modified:
  - web/src/app/go/[token]/page.tsx
  - web/src/app/go/[token]/GoRedirect.tsx
  - web/src/app/go/go-page.test.tsx
  - web/src/lib/redirect-allowlist.ts
  - web/src/lib/redirect-allowlist.test.ts
  - web/src/components/WatchCard.tsx
  - web/src/components/WatchCardActions.tsx
  - web/src/components/WatchCard.test.tsx
  - web/src/components/DeleteWatchDialog.tsx
  - web/src/components/NotificationHistory.tsx
  - web/src/components/NotificationHistory.test.tsx
  - web/src/app/manage/t/[token]/page.tsx
  - web/src/app/manage/manage-page.test.tsx
  - web/src/test/fixtures/manage.ts
  - web/src/test/fixtures/go.ts
autonomous: true
requirements: [FE-05, FE-06]

estimate:
  tokens: 98000
  raw_tokens: 98000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "FE-06 probe: `/go/[token]` fetches the API's JSON verdict SERVER-SIDE in the route's server component with no-store caching, then renders the outcome; a tiny client island performs only the delayed location replace. This avoids a cross-origin preflight on the most latency-sensitive page and loses no data, because the notification log stores no client address (D-116a, RESEARCH OQ-2)."
    - "FE-06 available state: renders the documented 'Still open — taking you to {platform}…' heading, the party, restaurant, date and time summary, a manual 'Take me there' button, and replaces the location after roughly 800 ms (D-116, UI-SPEC)."
    - "FE-06 gone state: renders the documented sympathetic copy — the table is gone, someone booked it first, the watch is still running — plus the estimated-window sentence ONLY when the API supplied one, a 'Keep watching' action and a link to the restaurant page. Never a countdown, never a taunt, never blaming the user (D-116, UI-SPEC)."
    - "The redirect target is validated against an allowlist of the two booking-platform hosts before any location replace; an unexpected host renders the manual link and performs no automatic navigation (RESEARCH Security → open redirect)."
    - "Every outbound link from a token-bearing page sets a no-referrer referrer policy so the token in the path cannot leak through a referrer header (RESEARCH Security → known threat patterns)."
    - "FE-05: `/manage/t/[token]` is a server shell that loads the manage bundle with the token as a path segment; mutations run in a client island with the token passed as a bearer header (D-115, D-91)."
    - "FE-05 empty probe: no watches renders the documented 'You don't have any watches yet' heading, body and browse action; a watch with no notification history renders the documented 'No alerts sent yet' copy (UI-SPEC empty states)."
    - "FE-05 adjacency probe: two watches with identical visible fields render as two distinct cards keyed by id; pausing one leaves the other untouched, and the two cards' controls target different watch ids."
    - "FE-05 ordering probe: watches render in the order the API returned them, and two watches with equal timestamps keep that order — the client applies no sort of its own."
    - "FE-05 idempotency probe: pausing an already-paused watch is a no-op that does not flip it back to active; issuing delete twice on the same watch leaves the same final state and shows no second confirmation."
    - "FE-05 concurrency probe: a failed optimistic mutation rolls back exactly the field it changed and surfaces a rollback toast; two in-flight mutations on different watches do not clobber each other's state."
    - "An invalid or expired token renders the documented 'This link has expired' copy with a browse action — never a crash, and never a distinction between an expired token and a token belonging to another user, because the API answers both with a not-found (D-115, RESEARCH Security V4)."
    - "The delete confirmation is a native modal dialog labelled by its heading and described by its body, with focus trapped by the platform, escape closing it, focus returning to the trigger, and the destructive action NOT autofocused (UI-SPEC Accessibility Contract → Dialogs)."
    - "Notification-outcome badges render as neutral badges differentiated by text plus a glyph — sent, delivered, clicked, still available and gone get no unique hues (UI-SPEC Component Inventory 4)."
    - "A paused watch is conveyed by a status badge and muted body ink, never by reduced opacity, which would push text below the contrast floor (UI-SPEC Component Inventory 8)."
    - "Editing expands the step-1 field set inline beneath the card body — no modal and no route change (D-115)."
    - "Loading and offline: the manage page renders two skeleton watch cards and three skeleton history rows in the real geometry; a null bundle renders the OfflineState band (UI-SPEC State Contracts)."
  artifacts:
    - web/src/app/go/[token]/page.tsx
    - web/src/app/go/[token]/GoRedirect.tsx
    - web/src/lib/redirect-allowlist.ts
    - web/src/components/WatchCard.tsx
    - web/src/components/WatchCardActions.tsx
    - web/src/components/DeleteWatchDialog.tsx
    - web/src/components/NotificationHistory.tsx
    - web/src/app/manage/t/[token]/page.tsx
    - web/src/test/fixtures/manage.ts
    - web/src/test/fixtures/go.ts
  key_links:
    - "`/go/[token]` consumes the JSON mode added to the Phase 4 route in 06-03; the 302 path is untouched and still serves SMS-opened links that land on the API host directly."
    - "`redirect_url` is produced by the API's own link builder (06-03); the frontend allowlist is defence in depth over that, not the only defence."
    - "The route is `/manage/t/[token]` because that is the path Phase 5 D-91 already builds into every management email; the looser wording in the requirements document is superseded and the reconciliation is recorded in the SUMMARY (RESEARCH OQ-6)."
    - "Mutations use the `ApiError`-throwing calls in `src/lib/api.ts`; the rollback toast is their consumer, which is why reads never throw and mutations may."
  prohibitions:
    - "The management token is never written to local storage, session storage, IndexedDB, a cookie, an analytics call or the console."
    - "No automatic navigation occurs to a host outside the booking-platform allowlist."
    - "No outbound link or form on a token-bearing page omits the no-referrer referrer policy."
    - "The manage page never distinguishes an expired token from another user's token in its copy or its status handling."
    - "Notification outcomes are never differentiated by colour alone."
    - "The paused state is never conveyed with reduced opacity."
    - "No client-side sort is applied to the watch list or the notification history."
  flagged_assumptions:
    - "RESEARCH A6: the manage bundle's exact shape — each watch with its last twenty notification-log rows including the slot-still-available field — is [ASSUMED] until Phase 5 has executed. Type it against the OpenAPI snapshot at execution time and keep every field-name mapping inside `src/lib/api.ts`."
    - "The UI-SPEC Page Layout Contracts row for `/go/[token]` says the whole page is a client island; D-116a is the later, research-informed amendment and supersedes it. The UI-SPEC's 'Checking that table…' loading state therefore applies to the client redirect island only, not to the initial fetch."
---

<objective>
Ship the two token-bearing pages: the alert landing that decides in one server round trip whether a table is still
there, and the management page where a user can pause, edit or delete a watch without ever signing in.

Purpose: FE-06 is the page a user reaches under time pressure, so its fetch happens server-side and its redirect is
validated before it fires. FE-05 is the page that has to be honest about what already happened, so its optimistic
mutations roll back visibly and its outcome badges are readable as text.

Output: the `/go/[token]` route with its redirect island and origin allowlist, the manage route with its watch cards,
delete dialog and notification history, and the fixtures and tests for both.
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
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-07-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| route | `/go/[token]` | server fetch, client island for the delayed replace only |
| component | `GoRedirect` | client island: the 800 ms delayed location replace |
| lib | `src/lib/redirect-allowlist.ts` | `isAllowedBookingUrl(url)` over the two platform hosts |
| route | `/manage/t/[token]` | server shell, client mutation island |
| component | `WatchCard` | status badge, field grid, inline edit |
| component | `WatchCardActions` | pause/resume, edit, delete with optimistic update and rollback |
| component | `DeleteWatchDialog` | native modal dialog, focus returned to trigger |
| component | `NotificationHistory` | per-watch table with text-plus-glyph outcome badges |
| fixtures | `src/test/fixtures/{go,manage}.ts` | typed, no network |

<tasks>

<task type="tracer">
  <name>Task 1: Tracer — `/go/[token]` fetches the verdict server-side and lands both outcomes</name>
  <files>web/src/lib/redirect-allowlist.ts, web/src/lib/redirect-allowlist.test.ts, web/src/app/go/[token]/page.tsx, web/src/app/go/[token]/GoRedirect.tsx, web/src/app/go/go-page.test.tsx, web/src/test/fixtures/go.ts</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-116 (the whole landing contract, both states, the retained 302 for non-JSON clients) and D-116a (server-side fetch plus a tiny client island for the delayed replace)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Copywriting Contract → the `/go/[token]` block (both states verbatim, and the three things it must never say), §State Contracts → the `/go/[token]` row, §Component Inventory item 1 (the primary button on each state)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Open Questions OQ-2 (why server-side wins and what is not lost) and §Security Domain → the open-redirect row
    - `docs/api.md` `/go` section as written in 06-03 — the JSON body's five fields
    - `.planning/phases/04-notification-pipeline/04-CONTEXT.md` — D-83 (the two platform booking URL shapes the allowlist must accept), D-84 (the click capture that happens on this same request)
    - `web/src/lib/api.ts` from 06-04 and `web/src/components/ui/Button.tsx` from 06-04
  </read_first>
  <action>
`src/lib/redirect-allowlist.ts`: a pure `isAllowedBookingUrl(url)` that parses the URL and returns true only for the
two booking-platform hosts the Phase 4 link builder produces (host equality or an exact subdomain suffix — never a
substring match, which would accept an attacker-controlled host ending in the same characters). Any parse failure
returns false. Add the comment recording that the API's own builder is the primary control and this is defence in
depth.

`src/app/go/[token]/page.tsx`: a server component that reads the JSON verdict through `src/lib/api.ts` with no-store
caching. A null result renders the documented error copy with a link to the restaurant. On a verdict, render the
available state or the gone state to the UI-SPEC copy exactly. The available state renders the heading naming the
platform, the party/restaurant/date/time summary, the manual primary button linking to the validated redirect URL,
and mounts the redirect island. The gone state renders the sympathetic copy, the estimated-window sentence ONLY when
the API supplied one, the keep-watching action and a link to the restaurant page. Set a no-referrer referrer policy
on every anchor on this page, because the token sits in the path.

`src/app/go/[token]/GoRedirect.tsx`: the client island, and the only client code on this page. It receives an
already-validated URL as a prop, waits roughly 800 ms and replaces the location. If the URL fails the allowlist the
server component does not mount the island at all — the island itself re-checks as a second line of defence and does
nothing when the check fails.

`src/test/fixtures/go.ts`: typed verdicts for the available case, the gone case with an estimated-window sentence,
the gone case without one, and a case whose redirect URL points at an unexpected host.

`src/app/go/go-page.test.tsx`: assert the available state renders the documented heading, the summary and the manual
button; the gone state renders the documented copy and includes the estimated-window sentence only when present; the
unexpected-host verdict renders the manual link and mounts no redirect island; a null verdict renders the error copy;
and no rendered string contains a taunting phrase — assert the absence of "Too slow", "You missed it" and any
countdown element. Run axe over each state.

`src/lib/redirect-allowlist.test.ts`: assert both platform hosts pass, a look-alike host that merely ends with the
same characters fails, a non-HTTPS URL fails, and an unparseable string fails.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/lib/redirect-allowlist.test.ts src/app/go/go-page.test.tsx` exits 0.
    - The allowlist test includes a look-alike host case that must return false.
    - `grep -c "use client" web/src/app/go/\[token\]/page.tsx` equals 0 and `grep -c "use client" web/src/app/go/\[token\]/GoRedirect.tsx` equals 1.
    - `grep -c 'referrerPolicy' web/src/app/go/\[token\]/page.tsx` is at least 1.
    - `grep -c 'location.replace' web/src/app/go/\[token\]/GoRedirect.tsx` equals 1 and the same string appears nowhere in `page.tsx`.
    - `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/lib/redirect-allowlist.test.ts src/app/go/go-page.test.tsx</automated>
  </verify>
  <done>A notification click lands on a page that already knows the answer, redirects only to a validated booking host, and says something kind when the table is gone.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Watch cards, optimistic mutations with rollback, and the delete dialog</name>
  <files>web/src/components/WatchCard.tsx, web/src/components/WatchCardActions.tsx, web/src/components/DeleteWatchDialog.tsx, web/src/components/WatchCard.test.tsx, web/src/test/fixtures/manage.ts</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-115 (the card contents, pause/resume, delete confirmation, inline edit, channel toggles, optimistic UI with a rollback toast)
    - `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md` — D-95 (the patch and delete endpoints, the editable field list, and the not-found-never-forbidden rule)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Component Inventory item 8 (WatchCard, the paused treatment and why opacity is forbidden) and item 5 (Toast, and that a toast is never the sole carrier of an error), §Accessibility Contract → Dialogs and → Focus, §Copywriting Contract → Buttons and → the destructive confirmation copy
    - `web/src/components/WatchForm/validation.ts` and the step-1 field set from 06-07 — the inline edit reuses them
    - `web/src/lib/api.ts` from 06-04 — the throwing mutation calls and `ApiError`
    - `web/src/components/ui/{Button,Card,Badge,Toast}.tsx` from 06-04
  </read_first>
  <behavior>
    - A card renders the restaurant name as its heading, a status badge reading Active or Paused, the party size, date range, time window, days of week and channels as labelled values, and three 44 px actions.
    - The paused rendering mutes the body ink and changes the badge text; no opacity class is applied.
    - Pausing applies the change optimistically, and on an API failure the state rolls back to exactly its previous value and a rollback toast appears.
    - Pausing an already-paused watch issues no state flip back to active.
    - Deleting opens a native modal dialog labelled by its heading and described by its body, with the destructive button not autofocused; escape closes it and focus returns to the trigger.
    - Confirming delete removes the card optimistically and, on failure, restores it with a rollback toast. A second confirm on an already-deleted watch produces the same final state and no second dialog.
    - Two cards rendered from two watches with identical visible fields have distinct keys and distinct control targets; acting on one does not change the other.
    - Editing expands the step-1 field set inline beneath the body — no dialog opens and the route does not change — and saving issues a patch with only the changed fields.
    - The rendered card set produces zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
`src/test/fixtures/manage.ts`: a typed manage bundle with at least four watches — one active, one paused, and two
with identical visible fields but distinct ids (the adjacency probe) — each with a notification history, including
one watch with an empty history.

`src/components/WatchCard.tsx`: the presentational card to the UI-SPEC contract. The paused treatment mutes the body
ink and changes the badge text; do not apply an opacity class, and add the comment recording that opacity would push
the text below the contrast floor.

`src/components/WatchCardActions.tsx`: the client island owning the mutations. Keep a local copy of each watch keyed
by id, apply a change optimistically, call the throwing mutation from `src/lib/api.ts`, and on an `ApiError` restore
the exact previous value for that watch alone and raise a rollback toast. Two in-flight mutations on different ids
must not share state — key every optimistic patch by watch id, never by index. Guard the no-op cases: a pause on an
already-paused watch and a delete on an already-removed watch both short-circuit.

`src/components/DeleteWatchDialog.tsx`: a native modal dialog opened programmatically, labelled by its heading and
described by its body, with the documented destructive copy naming the restaurant, the two documented buttons, the
destructive one NOT autofocused, escape closing, and focus returning to the trigger on close.

Inline edit reuses the step-1 field set and validation from 06-07 rendered beneath the card body, and saves with a
patch carrying only changed fields.

`src/components/WatchCard.test.tsx` asserts every behavior item with a stubbed global fetch, including both no-op
idempotency cases, the two-identical-watches adjacency case, and the concurrent-mutation case (two different ids in
flight). Run axe over the rendered set.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/components/WatchCard.test.tsx` exits 0.
    - The test asserts that after a failed pause the watch's status equals its pre-mutation value exactly and a rollback toast is present.
    - The test asserts two in-flight mutations on different watch ids both resolve without either overwriting the other.
    - `grep -cE 'opacity-[0-9]' web/src/components/WatchCard.tsx` equals 0.
    - `grep -c 'showModal' web/src/components/DeleteWatchDialog.tsx` equals 1 and `grep -c 'autoFocus' web/src/components/DeleteWatchDialog.tsx` equals 0.
    - `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/components/WatchCard.test.tsx</automated>
  </verify>
  <done>Watches can be paused, edited and deleted with optimistic feedback that rolls back visibly, and no mutation can touch a watch it did not target.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The manage page, its notification history and its expired-token state</name>
  <files>web/src/components/NotificationHistory.tsx, web/src/components/NotificationHistory.test.tsx, web/src/app/manage/t/[token]/page.tsx, web/src/app/manage/manage-page.test.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-115 (the page contract, the expired-token copy, the notification history with outcome badges)
    - `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md` — D-91 (the `/manage/t/{token}` path and the bearer alternative), D-95 (the bundle contents and the not-found-never-forbidden rule)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Component Inventory item 4 (outcome badges are text plus glyph, never unique hues), §State Contracts → the manage page and notification history rows, §Copywriting Contract → Empty states (the manage and history rows) and → Error and offline states (the expired-token row)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Security Domain → V4 (the frontend must not leak the difference between another user's watch and a missing one) and the referrer-leak row
    - `web/src/components/{WatchCard,WatchCardActions}.tsx` from Task 2 and `web/src/components/{EmptyState,OfflineState}.tsx` from 06-04
    - `web/src/lib/format.ts` from 06-04 — the timestamp formatting for history rows
  </read_first>
  <behavior>
    - The page loads the bundle server-side using the token path segment and renders one card per watch in the API's order, with no client-side sort.
    - An empty watch list renders the documented heading, body and browse action.
    - A watch with no notification history renders the documented history empty copy.
    - Each history row renders its outcome as a neutral badge carrying the outcome text plus a glyph; no outcome introduces a new hue, and the still-available and gone outcomes are distinguishable by text alone.
    - Timestamps render with tabular figures and the documented format.
    - An expired or unknown token renders the documented 'This link has expired' heading and body with a browse action, and the same copy is used for a token belonging to another user — the two are indistinguishable in the rendered output.
    - A null bundle from a reachable-but-failing API renders the OfflineState band.
    - Every anchor on the page sets a no-referrer referrer policy.
    - The token appears nowhere in browser storage, and the page contains no console call.
    - The assembled page produces zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
`src/components/NotificationHistory.tsx`: a per-watch table of the last notification-log rows with the outcome badge,
the channel, the timestamp and the still-available result. Outcomes render as neutral badges differentiated by text
plus a small inline glyph — a check for delivered, clicked and still-available, a slash for gone. Do not introduce
outcome colours; add the comment recording that five semantic hues would blow the accent budget and make colour the
only channel. The empty case renders the documented copy.

`src/app/manage/t/[token]/page.tsx`: the server shell. Read the bundle through `src/lib/api.ts` using the token path
segment. A null result caused by an invalid, expired or foreign token renders the documented expired-link copy with a
browse action — one rendering for all three, because the API answers a foreign watch with a not-found and the
frontend must not leak the distinction either. Render the page heading, then one `WatchCard` per watch with its
actions island and its history, in the API's order. Pass the token to the actions island as a prop for the bearer
header; never write it to any storage API, never log it, and set a no-referrer referrer policy on every anchor.
Render the documented skeletons for the loading state and the OfflineState band for a reachable-but-failing API.

`src/components/NotificationHistory.test.tsx` and `src/app/manage/manage-page.test.tsx` assert every behavior item
with a stubbed global fetch over the Task 2 fixtures, including the expired-token and foreign-token cases producing
identical rendered output. Add an assertion that no storage API was called with the token during the render (stub the
storage APIs and assert zero calls). Run axe over the assembled page.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/components/NotificationHistory.test.tsx src/app/manage/manage-page.test.tsx` exits 0.
    - The manage test asserts the rendered output for an expired token and for a foreign-user token are equal.
    - The manage test stubs the storage APIs and asserts they received zero calls containing the token.
    - `grep -rc 'localStorage\|sessionStorage' web/src/app/manage/ | grep -c ':[1-9]'` equals 0.
    - `grep -rc 'console\.' web/src/app/manage/ web/src/components/WatchCardActions.tsx | grep -c ':[1-9]'` equals 0.
    - `cd web && npm test` exits 0 (the whole frontend suite) and `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
    - `make web-build-offline` exits 0 with both new routes present.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test && npm run typecheck && npm run lint</automated>
  </verify>
  <done>A user with only a link can see, pause, edit and delete every watch, read what was already sent, and gets one honest message when the link no longer works.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| capability token in a URL path → page | the management and `/go` tokens are bearer capabilities carried in the address bar |
| API-supplied redirect URL → browser navigation | a URL from the API is used to navigate the user away |
| optimistic client state → user's belief | the UI reports success before the server has confirmed it |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-39 | Tampering | open redirect on `/go/[token]` | critical | mitigate | The URL is produced by the API's own builder (06-03) and re-validated by `isAllowedBookingUrl` before any navigation, with host equality or an exact subdomain suffix — never a substring match. An unexpected host renders a manual link and mounts no island |
| T-06-40 | Information disclosure | token leaking through a referrer header | high | mitigate | Every anchor on both token-bearing pages sets a no-referrer referrer policy; a grep asserts it on the `/go` page and the manage page test asserts it on the rendered output |
| T-06-41 | Information disclosure | token persisted on the device or logged | high | mitigate | The token is passed as a prop and a bearer header only. Grep gates assert no storage API and no console call under the manage tree, and the manage test stubs the storage APIs and asserts zero calls |
| T-06-42 | Information disclosure | enumeration via a distinguishable forbidden response | medium | mitigate | The API answers a foreign watch with a not-found (Phase 5 D-95); the page renders one identical message for expired, unknown and foreign tokens, asserted by an equality test on the rendered output |
| T-06-43 | Repudiation | optimistic success that never happened | high | mitigate | Every optimistic patch is keyed by watch id and restores its exact previous value on an `ApiError`, with a rollback toast; a test asserts the restored value equals the pre-mutation value |
| T-06-44 | Tampering | a mutation targeting the wrong watch | high | mitigate | Optimistic state is keyed by id, never by index; the adjacency test renders two watches with identical visible fields and asserts acting on one leaves the other unchanged |
| T-06-45 | Denial of service | repeated destructive action | low | mitigate | Pause and delete short-circuit when the watch is already in the target state; the dialog does not reopen for an already-deleted watch |
| T-06-SC | Tampering | npm installs | high | mitigate | This plan installs nothing — the dialog is the platform element, not a library. Recorded in the SUMMARY |
</threat_model>

<verification>
- `cd web && npm test && npm run typecheck && npm run lint && npm run build`
- `make web-build-offline`
</verification>

<success_criteria>
- `/go/[token]` decides server-side, redirects only to an allowlisted booking host, and its gone state is kind and honest.
- The manage page renders in the API's order, treats expired, unknown and foreign tokens identically, and never persists or logs the token.
- Optimistic mutations roll back to the exact previous value with a visible toast, are keyed by id, and are no-ops when already in the target state.
- Outcome badges and the paused state are readable without colour, and axe finds nothing on either page.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-08-SUMMARY.md` when done.
Record the reconciliation of the management route path (the requirements document says one thing, Phase 5 D-91 builds
another) so FE-05 is not later marked partially met, and paste the two booking hosts written into the allowlist.
</output>
