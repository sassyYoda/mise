---
phase: 06-pattern-intelligence-frontend-pwa
plan: 07
type: execute
wave: 7
depends_on: ["06-06"]
files_modified:
  - web/src/components/WatchForm/validation.ts
  - web/src/components/WatchForm/validation.test.ts
  - web/src/components/WatchForm/WatchForm.tsx
  - web/src/components/WatchForm/WatchForm.test.tsx
  - web/src/components/StepIndicator.tsx
  - web/src/app/watch/[slug]/page.tsx
  - web/src/app/watch/watch-page.test.tsx
  - web/src/lib/preview.ts
  - web/src/lib/preview.test.ts
  - web/src/components/NotificationPreview.tsx
  - web/src/lib/persist.ts
  - web/src/lib/outbox.ts
  - web/src/lib/outbox.test.ts
  - web/src/lib/push.ts
  - web/src/lib/push.test.ts
  - web/src/components/PushOptIn.tsx
  - web/src/components/PushOptIn.test.tsx
  - web/src/test/fixtures/notification-samples.json
  - scripts/dump_notification_samples.py
  - tests/unit/test_notification_samples_fixture.py
autonomous: true
requirements: [FE-03, FE-01]

estimate:
  tokens: 104000
  raw_tokens: 104000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "FE-03: `/watch/[slug]` is a two-step flow — Preferences then Contact — with a step indicator whose current step carries an aria-current of step and whose completed steps carry visually-hidden completion text; progress is never conveyed by colour alone (D-113, UI-SPEC Component Inventory 9)."
    - "FE-03 empty probe: step 1 opens with the documented DEFAULTS, not blank fields — party size 2 and a date range of today through fourteen days from today; optional fields (time window, days of week, seat type) left blank submit as ABSENT and the preview omits them rather than rendering an 'any' placeholder (D-113, UI-SPEC UI Considerations)."
    - "FE-03 empty probe, second half: an empty email produces the documented field-level error and focus moves to that field on a failed submit; the form is never submitted with a missing required field."
    - "FE-03 encoding probe: the email is trimmed and lower-cased before submission to match the API's identity rule; the phone is normalised to E.164 before submission and displayed in the documented US format; and the preview renders a non-ASCII restaurant name identically to the backend-rendered sample for the same input."
    - "Client-side validation mirrors the Phase 5 create-watch rules exactly — party size 1 through 10, end date at or after start date, a window of at most 60 days, start date not in the past in America/New_York, and a time window whose start is before its end — while the API remains the authority (RESEARCH Security V5)."
    - "Every validation message is the documented field-level string from the UI-SPEC error table; a 422 from the API maps to the field it names, and a non-field error renders above the submit button as an alert. A toast is never the sole carrier of a validation error (D-113, UI-SPEC A-7)."
    - "The notification preview is rendered from the SAME template wording the backend uses, and a parity test compares it against a checked-in JSON of backend-rendered samples produced by a pytest that dumps the notifier templates (D-113)."
    - "The preview card carries an accessible name describing it as a preview and is NOT a live region — it updates as the user types and would otherwise chatter (UI-SPEC Accessibility Contract → Forms)."
    - "Form state persists to session storage so an interrupted flow resumes, and the restored state re-renders step 1 with the user's values rather than the defaults (D-113)."
    - "A submission made while offline is queued in IndexedDB and replayed on the next online event, with the documented 'Saved — we'll send it when you're back' confirmation; the user is never told the watch was created when it was not (D-113, UI-SPEC error table)."
    - "The replay is idempotent: a queued submission that already succeeded is not sent twice, and a replay that fails leaves the item queued rather than dropping it."
    - "FE-01 push opt-in: the push channel row renders exactly one of five mutually exclusive states — unsupported browser, iOS outside standalone, permission default, permission granted, permission denied — and exactly one shows at a time (UI-SPEC Push-permission states)."
    - "In the denied state the enable button is REMOVED, not disabled: a disabled button implies retry is possible and it is not, because permission can only be reset in browser settings (UI-SPEC)."
    - "On iOS outside standalone the Add-to-Home-Screen explainer renders with its three-step list AND its closing line that email alerts work either way — the explainer must never read as a blocker for creating a watch (UI-SPEC)."
    - "Permission is requested only from a direct user interaction (a click handler), never on mount, because Safari requires it and because an on-mount prompt is hostile (RESEARCH Web Push facts)."
    - "The subscription posted to the API is the documented shape — endpoint plus a keys object with the two key fields — and it is sent with the management bearer token, never unauthenticated (D-117, RESEARCH Security)."
    - "Loading states: the submit button enters its pending state with its width locked so the layout does not jump, and the enable-notifications button enters a pending state while the subscription resolves (UI-SPEC UI Considerations)."
  artifacts:
    - web/src/components/WatchForm/validation.ts
    - web/src/components/WatchForm/WatchForm.tsx
    - web/src/components/StepIndicator.tsx
    - web/src/app/watch/[slug]/page.tsx
    - web/src/lib/preview.ts
    - web/src/components/NotificationPreview.tsx
    - web/src/lib/persist.ts
    - web/src/lib/outbox.ts
    - web/src/lib/push.ts
    - web/src/components/PushOptIn.tsx
    - web/src/test/fixtures/notification-samples.json
    - scripts/dump_notification_samples.py
  key_links:
    - "`src/lib/preview.ts` mirrors `services/notifier/templates.py`; `scripts/dump_notification_samples.py` renders the backend templates for a fixed input set into `web/src/test/fixtures/notification-samples.json`, and `tests/unit/test_notification_samples_fixture.py` keeps that file in sync so backend wording changes break the frontend parity test rather than drifting silently."
    - "`src/components/WatchForm/validation.ts` mirrors the Phase 5 create-watch model; the field names it produces are the ones `src/lib/api.ts` posts, so a 422 field path maps back without translation."
    - "`src/lib/push.ts` posts the subscription through `src/lib/api.ts` with the management token; the VAPID public key comes from the environment variable when present and otherwise from the API's public-key endpoint (D-110)."
    - "The service worker registered in 06-04 owns the push and click handlers; this plan owns only the subscription lifecycle in the page."
  prohibitions:
    - "Permission is never requested outside a click handler, and never on component mount."
    - "The enable-notifications button is never rendered disabled in the denied state — it is absent."
    - "A queued offline submission is never reported to the user as a created watch."
    - "The preview never invents wording: every string it renders is derived from the same template text the backend uses, and the parity test is the proof."
    - "No secret is read in this plan: only the three allowlisted public environment names may appear."
    - "An optional field left blank is never submitted as an empty string or as a placeholder value — it is omitted from the request body."
  flagged_assumptions:
    - "RESEARCH A3: iOS 16.4+ is assumed still to require Home Screen installation for Web Push as of 2026-09. If Apple has relaxed it, the gate is merely over-conservative and shows an unnecessary explainer — it never blocks a working path."
    - "RESEARCH A5/A6: the Phase 5 create-watch request body and its 422 error shape are [ASSUMED] until Phase 5 has executed. Type them against the OpenAPI snapshot at execution time and keep every field-name mapping inside `src/lib/api.ts`."
    - "The real-iPhone five-consecutive-push validation is human-gated and stays pending in `docs/runbooks/ios-pwa-push.md` (updated in plan 06-09). This plan proves the subscription flow's client logic only."
---

<objective>
Build the watch-setup flow: a two-step form with the documented defaults and validation, a notification preview that
is provably word-identical to what the backend will send, resilience across an interrupted or offline session, and a
push opt-in that tells the truth in all five of its permission states.

Purpose: FE-03 is the product's conversion path and the one place a user hands over contact details. Every promise it
makes — this is what the alert will look like, your details are still here, we'll create it when you're back online —
has to be literally true, which is why the preview is parity-tested against the backend and the offline queue is
tested for idempotency.

Output: the form and its validation, the preview and its parity oracle, the persistence and outbox modules, the push
opt-in island, and the assembled route.
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
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-06-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| route | `/watch/[slug]` | client-heavy by necessity; step 1 above the fold |
| component | `WatchForm` | two steps, validation, 422 mapping, pending submit, success screen |
| component | `StepIndicator` | two steps, aria-current, visually-hidden completion text |
| component | `NotificationPreview` | preview card, not a live region |
| component | `PushOptIn` | five mutually exclusive permission states |
| lib | `src/lib/validation` (in `WatchForm/`) | mirrors the Phase 5 create-watch rules |
| lib | `src/lib/preview.ts` | mirrors `services/notifier/templates.py` |
| lib | `src/lib/persist.ts` | session-storage save and restore |
| lib | `src/lib/outbox.ts` | IndexedDB queue plus an online-event replay |
| lib | `src/lib/push.ts` | `urlBase64ToUint8Array`, `pushGate`, `subscribeToPush` |
| script | `scripts/dump_notification_samples.py` | renders backend templates into the frontend fixture |
| fixture | `web/src/test/fixtures/notification-samples.json` | the parity oracle |

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Tracer — the two-step form validates, navigates and submits through a stubbed fetch</name>
  <files>web/src/components/WatchForm/validation.ts, web/src/components/WatchForm/validation.test.ts, web/src/components/WatchForm/WatchForm.tsx, web/src/components/WatchForm/WatchForm.test.tsx, web/src/components/StepIndicator.tsx, web/src/app/watch/[slug]/page.tsx, web/src/app/watch/watch-page.test.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-113 (both steps, the field list, the defaults, the maximum window, the submit path and the success screen)
    - `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md` — D-93 (the exact create-watch model and every validation rule), D-93a (today evaluated in America/New_York), D-90 (email identity)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Component Inventory items 3 and 9 (the Field sub-controls used in this phase — the stepper, date inputs, the day-of-week chip group, the seat-type radios, the email and phone inputs — and the StepIndicator contract), §Accessibility Contract → Forms and → Focus (the focus move to the step-2 heading), §Copywriting Contract → Buttons and the 422 field-level messages, §State Contracts → the watch-form row
    - `docs/api.md` create-watch section as written after 06-03, and `web/src/lib/api.ts` from 06-04
    - `web/src/components/ui/{Button,Field}.tsx` from 06-04
  </read_first>
  <behavior>
    - Step 1 mounts with party size 2 and a date range of today through fourteen days later, in America/New_York; no required field is blank on first render.
    - Party size below 1 or above 10 produces the documented message; an end date before the start date produces the documented message; a range longer than 60 days produces the documented message; a time window whose start is not before its end produces a message; a start date in the past produces a message.
    - Continue is blocked while step 1 has an error, and the first invalid field receives focus.
    - Advancing to step 2 moves focus to the step-2 heading, and the step indicator marks step 1 complete with visually-hidden completion text and step 2 current with aria-current.
    - An invalid email produces the documented message; choosing the SMS channel reveals a phone field and requires a valid US number; the email channel is always on and cannot be removed.
    - Submitting posts exactly the documented body with optional blank fields ABSENT (not empty strings) and, on success, renders the success screen with the management link and the emailed-it note.
    - A 422 whose body names a field renders that message at that field; a 5xx renders the documented non-field error above the submit button as an alert and keeps every entered value.
    - The submit button enters its pending state with a locked width while the request is in flight.
    - The rendered form produces zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
`src/components/WatchForm/validation.ts`: a pure module mirroring the Phase 5 create-watch rules. Export a
`WatchDraft` type, a `defaults(now)` factory producing the documented step-1 defaults with `now` passed in (no clock
read inside), a `validateStep1(draft, now)` and a `validateStep2(draft)` each returning a map of field name to
message using the exact UI-SPEC strings, and a `toRequestBody(draft)` that OMITS every optional field left blank
rather than sending an empty string. Normalise the email by trimming and lower-casing and the phone to E.164 inside
`toRequestBody`. Date arithmetic uses America/New_York so "today" matches the API's rule.

`src/components/StepIndicator.tsx`: the two-step indicator to the UI-SPEC contract — an ordered list, a circular
marker per step, aria-current on the current step, visually-hidden completion text on completed steps, and a
container label. Never convey progress by colour alone.

`src/components/WatchForm/WatchForm.tsx`: the client island. Step 1 renders the party-size stepper (two 44 px buttons
flanking a real number input with a polite live announcement of its value), the date inputs, the optional time-window
selects, the optional day-of-week chip group as a labelled group of pressed-state buttons at 44 px, and the optional
seat-type radios. Step 2 renders the email field, the channel controls (email always on; SMS revealing a phone field
with the documented input mode and autocomplete), and the submit button. Navigation moves focus to the step-2
heading. Submission goes through `src/lib/api.ts`; a 422 maps by field path onto the field map and a non-field error
renders above the submit button with an alert role. On success render the success screen with the management link,
the emailed-it note and the documented next-step button.

`src/app/watch/[slug]/page.tsx`: a thin server shell that reads the restaurant through `src/lib/api.ts` for the
header, renders the step indicator and the form island, and renders the documented not-found copy when the
restaurant is null.

For this tracer the preview card, the session-storage resume, the offline outbox and the push row are absent — each
is added in Task 2 or Task 3 without changing the form's structure. Leave a named slot in step 2 where the preview
and the push row will mount so neither addition is a restructure.

Both test modules assert the behavior block with a stubbed global fetch and typed fixtures, and run axe over the
rendered form.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/components/WatchForm/validation.test.ts src/components/WatchForm/WatchForm.test.tsx src/app/watch/watch-page.test.tsx` exits 0.
    - The validation test asserts that a draft with every optional field blank produces a request body whose keys do not include the optional field names.
    - `grep -cE 'Date\.now|new Date\(\)' web/src/components/WatchForm/validation.ts` equals 0 (every rule takes an explicit reference time).
    - `grep -c 'aria-current' web/src/components/StepIndicator.tsx` is at least 1.
    - `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/components/WatchForm src/app/watch</automated>
  </verify>
  <done>A user can complete both steps and create a watch against a stubbed API, with the documented defaults, the documented messages and a success screen.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Notification preview and its backend parity oracle</name>
  <files>web/src/lib/preview.ts, web/src/lib/preview.test.ts, web/src/components/NotificationPreview.tsx, web/src/test/fixtures/notification-samples.json, scripts/dump_notification_samples.py, tests/unit/test_notification_samples_fixture.py</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-113 (the preview mirrors the backend template wording and a Vitest test compares against a checked-in JSON of backend-rendered samples)
    - `.planning/phases/04-notification-pipeline/04-CONTEXT.md` — D-81 (the template contents for email, SMS and push; the estimated-window line) and D-81a (the SMS GSM-7 constraint and the omitted URL scheme)
    - `services/notifier/templates.py` as Phase 4 shipped it — the exact strings and the substitution mechanism; this is the source of truth the preview mirrors
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Accessibility Contract → Forms (the preview card is labelled but is not a live region) and §Copywriting Contract
    - `scripts/` — the repo's existing script style, and `Makefile` for how scripts are invoked
    - `web/src/lib/format.ts` from 06-04
  </read_first>
  <behavior>
    - For each of at least six fixed inputs — covering one and two guests, a seat type present and absent, an estimated-window line present and absent, and a restaurant name containing a non-ASCII character — the preview's email subject, email body, SMS body and push body equal the backend-rendered sample byte for byte.
    - The SMS sample in the fixture is at most 160 characters for every input, matching the Phase 4 constraint.
    - When the estimated-window line is absent the preview renders no blank line and no placeholder where it would have been.
    - The preview omits an optional field the user left blank rather than rendering an 'any' placeholder.
    - The preview card carries an accessible name describing it as a preview and has no live-region attribute.
    - Regenerating the fixture from the backend templates produces a byte-identical file when the templates have not changed.
  </behavior>
  <action>
`scripts/dump_notification_samples.py`: a small async-free script that imports `services/notifier/templates.py`,
renders each channel for a fixed, in-file list of at least six input records (covering the cases in the behavior
block), and writes them to `web/src/test/fixtures/notification-samples.json` with sorted keys and a trailing newline
so the file is diff-stable. Module docstring cites D-113 and PATTERN-03 and ends with a `Named symbols:` line. The
input list is a module constant, not generated, so the file is reproducible.

`tests/unit/test_notification_samples_fixture.py`: regenerate the samples in memory and assert they equal the
checked-in file byte for byte. This is what makes a backend wording change break the build instead of silently
drifting away from the frontend preview.

`src/lib/preview.ts`: pure functions rendering the same four strings from a `WatchDraft` plus a hypothetical slot,
mirroring the backend template wording exactly. Do not paraphrase, do not improve the copy, and do not add a field
the backend does not render — the parity test is the contract. Where the backend omits a line on a missing value, omit
it identically.

`src/lib/preview.test.ts`: load the checked-in fixture and assert equality for every input in it. This is the FE-03
encoding probe: it proves the non-ASCII restaurant name renders identically on both sides.

`src/components/NotificationPreview.tsx`: the preview card mounted into the step-2 slot, rendering the email and (when
selected) the SMS and push previews from the live draft. Give it an accessible name describing it as a preview of the
alert the user will receive, and do NOT make it a live region — it updates on every keystroke and would otherwise
chatter. Add that reason as a comment.
  </action>
  <acceptance_criteria>
    - `uv run python scripts/dump_notification_samples.py && git diff --exit-code web/src/test/fixtures/notification-samples.json` exits 0 (the fixture is reproducible).
    - `uv run pytest tests/unit/test_notification_samples_fixture.py -x -q` exits 0.
    - `cd web && npm test -- src/lib/preview.test.ts` exits 0.
    - `node -e "const s=require('./web/src/test/fixtures/notification-samples.json');const bad=Object.values(s).filter(v=>v.sms&&v.sms.length>160);process.exit(bad.length)"` exits 0.
    - `grep -c 'aria-live' web/src/components/NotificationPreview.tsx` equals 0.
    - `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_notification_samples_fixture.py -x -q && cd web && npm test -- src/lib/preview.test.ts</automated>
  </verify>
  <done>What the preview shows and what the backend will send are the same strings, proven by a reproducible fixture on both sides of the language boundary.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Session resume, the offline outbox, and the five-state push opt-in</name>
  <files>web/src/lib/persist.ts, web/src/lib/outbox.ts, web/src/lib/outbox.test.ts, web/src/lib/push.ts, web/src/lib/push.test.ts, web/src/components/PushOptIn.tsx, web/src/components/PushOptIn.test.tsx, web/src/components/WatchForm/WatchForm.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-113 (session-storage resume, the IndexedDB queue and the simple online-event replay, the push gating), D-117 (the subscribe call and where the subscription is posted)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §State Contracts → Push-permission states (all five rows and the Add-to-Home-Screen explainer with its exact copy) and §Copywriting Contract → "Error and offline states" (the offline-queued confirmation and the push-denied copy)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Code Examples → "urlBase64ToUint8Array and the push opt-in flow" (the verified helper, the gate function and its three refusal reasons, and the user-gesture requirement) and §Common Pitfalls → Pitfall 3
    - `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md` — D-102 (the push subscribe endpoints and the bearer requirement)
    - `web/src/lib/api.ts` from 06-04, `web/src/components/ui/{Button,Badge,Toast}.tsx` from 06-04
  </read_first>
  <behavior>
    - `urlBase64ToUint8Array` converts a known VAPID public key to a 65-byte array; padding and the two URL-safe character substitutions are handled.
    - `pushGate` returns unsupported when the service worker or push manager APIs are absent, needs-install for an iOS user agent outside standalone display mode, denied when permission is denied, and ok otherwise.
    - `subscribeToPush` requests permission and returns null when it is not granted; on grant it returns the documented subscription shape.
    - `PushOptIn` renders exactly one of the five states at a time; in the denied state no enable button exists in the DOM at all; in the granted state a neutral badge with a check glyph renders and the button is gone; in the needs-install state the three-step explainer renders including its closing line that email alerts work either way.
    - Clicking enable moves the button into its pending state and resolves into either the granted badge or the denied copy; permission is never requested outside that click handler.
    - `persist` saves the draft to session storage on change and restores it on mount, so a reload mid-flow re-renders step 1 with the user's values rather than the defaults; clearing happens on successful submission.
    - `outbox` queues a submission when the browser reports offline, shows the documented saved-for-later confirmation rather than a success screen, and replays on the next online event.
    - Replay idempotency: replaying a queued item that already succeeded does not send it twice; a replay that fails leaves the item in the queue.
    - The rendered opt-in produces zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
`src/lib/push.ts`: copy the verified helper and gate from the research code example — the base64url decoder, the
`pushGate` returning the three refusal reasons, and `subscribeToPush` which requests permission and then subscribes
with the user-visible-only flag and the decoded application server key. The VAPID public key is read from the
allowlisted public environment variable when set and otherwise fetched from the API's public-key endpoint through
`src/lib/api.ts`. Post the resulting subscription through `src/lib/api.ts` with the management bearer token — never
unauthenticated. Add the comment recording that permission must be requested from a direct user interaction and that
this function must therefore only ever be called from a click handler.

`src/components/PushOptIn.tsx`: the five mutually exclusive renderings from the UI-SPEC table, chosen by `pushGate`
and the current permission value. The denied rendering REMOVES the button rather than disabling it — a disabled
button implies a retry that is genuinely impossible in-page; write that reason as a comment. The needs-install
rendering is the Add-to-Home-Screen explainer on the sunken surface with its ordered three steps, the inline share
glyph, and its closing line that the user can skip this because email alerts work either way. That closing line is
required: the explainer must never read as a blocker.

`src/lib/persist.ts`: save and restore the draft under a namespaced session-storage key, guarding for environments
without the API. Restore on mount before the defaults are applied so a resumed flow shows the user's values. Clear on
successful submission. Never write the management token or any credential here.

`src/lib/outbox.ts`: an IndexedDB queue with add, list, remove and a `replay(send)` function, plus a listener
registration for the online event. No background-sync dependency and no third-party wrapper. Each queued item carries
a client-generated id and a status so a replay can be idempotent: mark an item sent before removing it and skip items
already marked. A failed replay leaves the item queued.

Wire all three into `WatchForm`: mount `NotificationPreview` and `PushOptIn` into the step-2 slots left by Task 1;
restore and persist the draft; and on submit, when the browser reports offline, queue instead of posting and render
the documented saved-for-later confirmation with the toast rather than the success screen.

Test modules assert every behavior item. Use a fake IndexedDB shim or a thin in-memory adapter behind the outbox's
storage seam rather than adding a dependency; stub `Notification`, `navigator.serviceWorker` and the display-mode
media query with `vi.stubGlobal`. Run axe over the rendered opt-in.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/lib/push.test.ts src/lib/outbox.test.ts src/components/PushOptIn.test.tsx` exits 0.
    - The push test asserts the decoded key length is 65 bytes and that `pushGate` returns the needs-install reason for an iOS user agent outside standalone.
    - The PushOptIn test asserts that in the denied state the enable button is absent from the DOM (a query for it returns null), not merely disabled.
    - `grep -c 'requestPermission' web/src/components/PushOptIn.tsx` equals 0 (the request happens in `src/lib/push.ts`, called from the click handler).
    - `grep -rc 'localStorage' web/src/lib/persist.ts` equals 0 (session storage only).
    - `cd web && npm test` exits 0 (the whole frontend suite) and `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test && npm run typecheck && npm run lint</automated>
  </verify>
  <done>An interrupted flow resumes, an offline submission is honestly queued and idempotently replayed, and the push row tells the truth in all five permission states.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| user input → API | email, phone and watch preferences leave the browser |
| browser storage → later sessions | draft state and queued submissions persist on the device |
| push service → subscription | a push endpoint and key pair are created and sent to the API |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-33 | Information disclosure | credentials in browser storage | high | mitigate | `persist` stores only the draft preferences in SESSION storage and never a token; the outbox stores the submission body and a status, never a credential; a grep asserts local storage is unused |
| T-06-34 | Spoofing | an unauthenticated push subscription bound to someone else's watch | high | mitigate | The subscribe call is posted with the management bearer token per Phase 5 D-102; the client never posts a subscription without one |
| T-06-35 | Repudiation | telling a user a watch was created when it was queued | high | mitigate | The offline path renders the documented saved-for-later confirmation, never the success screen; the replay marks an item sent before removal so a double-send cannot occur |
| T-06-36 | Tampering | client-side validation trusted as authoritative | medium | accept | The client mirrors the Phase 5 rules for UX only; the API remains the authority and its 422 responses map back onto fields. Accepted because the server-side rules are unchanged and independently tested |
| T-06-37 | Information disclosure | a phone number retained in a rendered preview or a log | medium | mitigate | The preview renders the message templates, not the contact details; nothing in this plan logs a draft, and the API returns only a masked phone |
| T-06-38 | Denial of service | iOS revoking the push subscription | high | mitigate | The subscription is gated behind standalone display mode on iOS, and the service worker's handler (06-04) wraps its whole chain and always supplies a body. The five-consecutive-push device test stays human-gated |
| T-06-SC | Tampering | npm installs | high | mitigate | This plan installs nothing — no IndexedDB wrapper, no validation library, no background-sync package. Recorded in the SUMMARY |
</threat_model>

<verification>
- `cd web && npm test && npm run typecheck && npm run lint && npm run build`
- `uv run pytest tests/unit -x -q -W error::RuntimeWarning`
- `uv run python scripts/dump_notification_samples.py && git diff --exit-code web/src/test/fixtures/notification-samples.json`
- `make web-build-offline`
</verification>

<success_criteria>
- Step 1 opens with the documented defaults, every documented validation message is reachable, and optional blanks are omitted from the request body.
- The preview equals the backend-rendered samples byte for byte across at least six inputs including a non-ASCII name.
- An interrupted flow resumes from session storage; an offline submission is queued, honestly labelled and idempotently replayed.
- Exactly one of five push states renders, the denied state has no button, and the iOS explainer never reads as a blocker.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-07-SUMMARY.md` when done.
Record the exact create-watch request body the form posts (field names as they appear on the wire) and any place the
assumed Phase 5 shape had to change, so a reviewer can confirm the change stayed inside `src/lib/api.ts`.
</output>
