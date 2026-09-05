---
phase: 06-pattern-intelligence-frontend-pwa
plan: 05
type: execute
wave: 5
depends_on: ["06-04"]
files_modified:
  - web/src/lib/heatmap.ts
  - web/src/lib/heatmap.test.ts
  - web/src/components/Heatmap.tsx
  - web/src/components/Heatmap.test.tsx
  - web/src/components/PatternCard.tsx
  - web/src/components/PatternCard.test.tsx
  - web/src/components/RecentEvents.tsx
  - web/src/components/RecentEvents.test.tsx
  - web/src/components/icons/index.tsx
  - web/src/app/restaurant/[slug]/page.tsx
  - web/src/app/restaurant/restaurant-page.test.tsx
  - web/src/test/fixtures/heatmap.ts
  - web/src/test/fixtures/restaurant.ts
autonomous: true
requirements: [FE-04, PATTERN-02]

estimate:
  tokens: 96000
  raw_tokens: 96000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "The heatmap is a server-rendered SVG with no chart library and no client JavaScript — `/restaurant/[slug]` stays a pure server component, which is what protects the LCP budget (D-114, UI-SPEC A-8)."
    - "FE-04 boundary probe: `bucket(count, max)` returns step 1 at a ratio of exactly 0.20, step 2 one step above it, and step 5 when `count === max`; the ramp bands are lower-exclusive and upper-inclusive throughout (UI-SPEC Heatmap Color Scale)."
    - "FE-04 precision probe: `bucket` derives its ratio from `count / max` where `max` comes from the API payload and is NEVER recomputed client-side (D-107); `max === 0` short-circuits with no division."
    - "FE-04 empty probe: a payload whose cells are all zero renders the full 7x24 hatched grid plus the documented 'Not enough history yet' copy — the grid is never blanked, so the reader can see that collection is working (UI-SPEC UI Considerations)."
    - "FE-04 encoding probe: each cell's accessible name uses the full day name, a 12-hour clock label and either the exact opening count or the documented not-enough-data phrasing; counts render with tabular figures (UI-SPEC Accessibility Contract)."
    - "A cell flagged `sparse` by the server renders gray fill PLUS a diagonal hatch pattern and says so in its accessible name, at every count including the maximum — lightness alone cannot separate the sparse gray from ramp steps 1 and 2 (UI-SPEC A-4, RESEARCH Pitfall 7)."
    - "The heatmap is ONE tab stop: exactly one cell carries a zero tabindex (the highest-count cell) and every other carries minus one; arrow keys move focus and Home/End jump to row start and end (UI-SPEC Accessibility Contract)."
    - "The legend has six entries — five ramp swatches labelled with their NUMERIC ranges derived from `max`, then the hatched sparse swatch labelled with the fewer-than-ten-observations wording. A legend of unlabelled swatches is a defect (UI-SPEC Legend)."
    - "The heatmap's y-axis is the SERVICE weekday (`day_of_week`, Sunday first) and the x-axis is the observation hour in America/New_York, and the caption says so (D-114, BC-11, RESEARCH OQ-1)."
    - "The `sample` prop renders the accent-outline 'Sample data' badge and prefixes the container's accessible name, so the home-page fixture can never be mistaken for live data (D-112, CONTEXT specific ideas)."
    - "PATTERN-02 partial probe: `PatternCard` renders `summary_text` verbatim plus one chip per DETECTED rule with its CI text; an undetected rule appears in no visual treatment at all — not grayed, not labelled not-detected, not a zero-state chip (D-106, UI-SPEC Component Inventory 10)."
    - "When `status` is `collecting_data` the card renders the exact quantified placeholder plus a thin progress hairline against the 14-day threshold, and no chips and no partial summary (D-108, UI-SPEC)."
    - "The card tolerates a `ready` status with a missing report by falling back to the placeholder rather than rendering an empty card (RESEARCH Pitfall 8)."
    - "`/restaurant/[slug]` renders, above the fold: the cover image through the image component, the name as the page's single h1, the meta line, the active-watch-count badge as a NEUTRAL badge, and the 'Add to watchlist' primary CTA linking to `/watch/[slug]` (D-114, UI-SPEC Page Layout Contracts)."
    - "The meta line wraps and never truncates; at 320 px the longest seeded combination wraps to two lines by design (UI-SPEC)."
    - "Every data-bearing surface on the page implements its loading, empty, error and offline renderings from the UI-SPEC State Contracts table: a skeleton grid in the real 7x24 geometry, a skeleton of three prose lines and two chips for the card, five skeleton rows for recent events, and the OfflineState band in place of any surface whose fetch returned null."
    - "A 404 from the restaurant fetch renders the documented 'We don't watch that restaurant' copy with a browse action, never a crash (UI-SPEC error table)."
  artifacts:
    - web/src/lib/heatmap.ts
    - web/src/components/Heatmap.tsx
    - web/src/components/PatternCard.tsx
    - web/src/components/RecentEvents.tsx
    - web/src/app/restaurant/[slug]/page.tsx
    - web/src/test/fixtures/heatmap.ts
    - web/src/test/fixtures/restaurant.ts
  key_links:
    - "`Heatmap` consumes the D-107 payload directly: `cells`, `max`, `days`, `hours`, `windowDays`, and each cell's server-computed `sparse` flag. It derives no threshold of its own."
    - "`PatternCard` consumes the `PatternReport` shape from `GET /api/restaurants/{slug}/pattern`; `pattern_status` on the detail response comes from the same cached value (06-03), so the page can choose its rendering without a second request."
    - "The page reads through `src/lib/api.ts` only; a null result from any of its three fetches selects that surface's OfflineState rather than failing the render."
    - "`bucket()` lives in `src/lib/heatmap.ts` as a pure function so the home page's sample fixture and the live detail page share exactly one colour mapping."
  prohibitions:
    - "The heatmap never renders a cell as a ramp colour when the server flagged it sparse, at any count including the maximum."
    - "The heatmap never recomputes `max` from the cells it was given."
    - "`summary_text` is rendered as text; React's raw-HTML injection prop is not used (the Task-1 gate from 06-04 covers the whole tree)."
    - "No chart library, no charting dependency and no client-side JavaScript is added for the heatmap; `/restaurant/[slug]` declares no client directive."
    - "No pattern chip renders a percentage without its sample size beside it."
    - "The active-watch-count badge is never accent-coloured — accent is reserved to the closed list in the UI-SPEC."
  flagged_assumptions:
    - "UI-SPEC unresolved item (overflow / media): the heatmap `viewBox` scales linearly, so above 1152 px the cells become large and airy and below 320 px the 11 px axis labels approach illegibility. No max-width is fixed for the heatmap card. Assumption carried: the 72 rem content max-width plus 24 columns keeps cells in a reasonable range. Revisit if the visual audit finds either extreme unattractive."
    - "RESEARCH OQ-1 (which weekday the y-axis means) is resolved as the SERVICE weekday per D-114's literal wording, with the axis captions naming both axes explicitly. Do not re-litigate during the phase; revisit after the first real 30-day window."
---

<objective>
Build the restaurant detail page: a server-rendered SVG heatmap that cannot over-claim, a pattern card that never
hedges, and a page that degrades into readable states when any of its three fetches fails.

Purpose: FE-04 is where PATTERN-01 and PATTERN-02 become visible. The honesty contract — sparse cells texturally
distinct, undetected rules omitted entirely, every percentage carrying its sample size — is enforced here in markup
and in tests, on top of the server-side flags from 06-02.

Output: `src/lib/heatmap.ts`, three components, the detail route, two fixture modules and four test modules.
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
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-04-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| route | `/restaurant/[slug]` | server component, no client island |
| component | `Heatmap` | server-rendered SVG, one tab stop, CSS-only tooltip |
| component | `PatternCard` | two mutually exclusive renderings |
| component | `RecentEvents` | last 10 openings, with its empty state |
| lib function | `bucket(count, max) -> 1..5` | pure ramp mapping, shared with the home sample |
| lib constants | `DAYS`, `HOUR_LABELS`, `SPARSE_THRESHOLD_LABEL`, `VIEWBOX` | heatmap geometry and labels |
| fixtures | `src/test/fixtures/heatmap.ts`, `src/test/fixtures/restaurant.ts` | typed, no network |

<tasks>

<task type="tracer">
  <name>Task 1: Tracer — the detail route renders a real heatmap SVG from a payload</name>
  <files>web/src/lib/heatmap.ts, web/src/lib/heatmap.test.ts, web/src/components/Heatmap.tsx, web/src/app/restaurant/[slug]/page.tsx, web/src/test/fixtures/heatmap.ts, web/src/test/fixtures/restaurant.ts</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Heatmap Color Scale (the five ramp steps in both schemes, the sparse fill and hatch, cell geometry, the legend contract) and §Component Inventory item 6 (the exact signature, viewBox arithmetic, gutters and label sizes)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-114 (axes, 5-step scale, sparse gray, keyboard-focusable cells), D-107 (the payload shape and `max`)
    - `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/web/src/components/Heatmap.tsx` and its test — the data contract, the pure scale function and the 168-labelled-cell assertion, all executed green. The markup is a table there and must become SVG here
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md` → "`web/src/components/Heatmap.tsx`" — what to keep from the analog and what the UI-SPEC supersedes
    - `docs/api.md` heatmap section as written in 06-03, and `web/src/lib/api.ts` from 06-04 — the exact payload type
    - `web/src/app/globals.css` — the token names the ramp and hatch consume
  </read_first>
  <action>
`src/lib/heatmap.ts`: the pure layer. Export the seven day labels with Sunday first (matching the backend's 0=Sun
convention), the hour labels rendered every third hour, and `bucket(count, max)` returning 1 through 5 against the
UI-SPEC ranges — lower-exclusive, upper-inclusive, with `max === 0` short-circuiting before any division and a count
of zero producing no ramp step. Export the viewBox geometry constants derived from the spec arithmetic: a 16-unit
cell, a 2-unit gap, a 2-unit corner radius, a 34-unit left gutter for day labels and an 18-unit bottom gutter for
hour labels, with the overall width and height computed from them rather than written as literals. Export the
`Cell` type mirroring the API payload's per-cell shape including its server-supplied `sparse` flag.

`src/components/Heatmap.tsx`: a server component taking the D-107 payload plus an optional `sample` flag. Render an
SVG with the computed viewBox, full width, automatic height and a preserve-aspect-ratio value that keeps the grid
centred. Define the diagonal hatch pattern ONCE in the SVG defs and reference it from every sparse cell. Each cell is
a group containing a rect whose fill is either the ramp step from `bucket` or the sparse gray, and — when sparse — a
second rect filled with the hatch reference. Day labels sit in the left gutter, hour labels in the bottom gutter, at
the 11 px weight-600 exception size, in the muted ink token. Take `max` from the payload; never derive it from the
cells.

For this tracer the cells, their fills, the hatch and both axis label sets are enough — the accessible names, the
roving tabindex, the tooltip and the legend land in Task 2. Do not stub anything that would need an architectural
change to fill in: the cell group is already the element that will carry the tabindex and the tooltip.

`src/test/fixtures/heatmap.ts`: three typed payloads — a populated 7x24 grid with a known `max` and a known
highest-count cell, an all-zero grid, and a mixed grid with a cell at exactly 9 observations and a cell at exactly
10. `src/test/fixtures/restaurant.ts`: a typed restaurant detail payload matching the 06-03 response shape,
including `pattern_status`, `active_watch_count`, `cover_photo_url` on a host present in `images.remotePatterns`,
and a recent-events list.

`src/app/restaurant/[slug]/page.tsx`: a server component that reads the restaurant detail and the heatmap through
`src/lib/api.ts`, renders the header block (cover image with the priority flag, the name as the single h1, the meta
line, the neutral active-watch-count badge, the primary CTA linking to the watch route) and the heatmap below it. A
null restaurant result renders the documented not-found copy; a null heatmap result renders the OfflineState in place
of the heatmap card. Declare no client directive anywhere in this file.

`src/lib/heatmap.test.ts` for this task asserts the ramp boundaries: a ratio of exactly 0.20 is step 1, one step
above is step 2, `count === max` is step 5, `max === 0` is handled without division, and the geometry constants
produce the expected viewBox dimensions.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/lib/heatmap.test.ts` exits 0.
    - `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
    - `grep -c "use client" web/src/app/restaurant/\[slug\]/page.tsx` equals 0 and `grep -c "use client" web/src/components/Heatmap.tsx` equals 0.
    - `grep -c '<table' web/src/components/Heatmap.tsx` equals 0 (the markup is SVG, not a table).
    - The rendered heatmap exposes an SVG root with a scaling view box — asserted in the component test, not by grep.
    - `grep -cE 'max\s*=\s*Math\.max' web/src/components/Heatmap.tsx` equals 0 (max is never recomputed).
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/lib/heatmap.test.ts && npm run build</automated>
  </verify>
  <done>The detail route renders a real 168-cell SVG heatmap from a payload, with the ramp, the hatch and both axes, entirely server-side.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Heatmap accessibility, tooltip and legend — the honesty contract in markup</name>
  <files>web/src/components/Heatmap.tsx, web/src/components/Heatmap.test.tsx, web/src/components/icons/index.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Accessibility Contract → Heatmap (grid roles, the roving tabindex rationale, both accessible-name forms, the focus ring inside the SVG, the WCAG 2.5.8 Essential exemption) and §Heatmap Color Scale → Legend
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Component Inventory item 6 → Tooltip (the CSS/SVG-only mechanism, the tip text formats, the right-edge anchoring rule) and the `sample` prop behaviour
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Copywriting Contract → Empty states → the heatmap row
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Common Pitfalls → Pitfall 7 (the over-claiming heatmap and the sparse-at-every-count assertion) and §Code Examples → "axe in a component test"
    - `web/src/components/Heatmap.tsx` and `web/src/lib/heatmap.ts` as written in Task 1
  </read_first>
  <behavior>
    - The SVG carries a grid role, an accessible name naming the metric and the window, and a reference to the legend as its description; each day row carries a row role and each cell a gridcell role.
    - Exactly one cell in the whole grid carries a zero tabindex and it is the highest-count cell; every other cell carries minus one. Rendering the all-zero fixture still produces exactly one zero-tabindex cell.
    - A non-sparse cell's accessible name contains the full day name, a 12-hour label and the exact opening count; a sparse cell's name contains the documented not-enough-data phrasing instead of a count.
    - A cell the server flagged sparse renders the hatch reference and the gray fill even when its count equals `max` — the sparse category beats the ramp at every count.
    - The legend renders exactly six entries: five ramp swatches each labelled with a numeric range derived from `max`, then the hatched swatch with the fewer-than-ten-observations label.
    - The all-zero fixture renders all 168 cells plus the documented 'Not enough history yet' heading and body beneath the grid — the grid is not blanked.
    - With the `sample` flag set, an accent-outline badge reading 'Sample data' renders above the grid and the container's accessible name is prefixed accordingly.
    - Rendering any fixture produces zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
Complete the heatmap to the UI-SPEC accessibility and legend contract.

Add the grid, row and gridcell roles and the container's accessible name and description reference. Compute the
roving tabindex once from the payload — the index of the highest-count cell, resolved deterministically (first
occurrence in row-major order on a tie) so the rendering is stable. Every other cell gets minus one. Add the arrow,
Home and End key handling as declarative attributes plus the CSS that draws the focus ring inside the SVG on the
focused group; because the page has no client island, the key handling must be expressed in a way that survives
server rendering — if a small amount of behaviour genuinely cannot be expressed without script, add it as a tiny
client island scoped to the grid and record the deviation in the SUMMARY rather than dropping the requirement.

Give each cell group a title element carrying its tip text in the documented format, plus a sibling tip group that is
transparent by default and becomes visible on hover and on focus-visible of the parent group — CSS and SVG only, no
positioning library and no measurement at runtime. Cells in the rightmost columns anchor their tip text to the end,
chosen from the cell's column index rather than from a measured width.

Render the legend beneath the grid in the label type and muted ink, with five numeric ranges computed from `max`
plus the hatched sparse entry. The numeric ranges are the non-colour channel that keeps the chart compliant; an
unlabelled swatch row is a defect.

When every cell is sparse, render the documented empty-state heading and body beneath the grid while keeping the
full grid visible.

Implement the `sample` flag: the accent-outline badge above the grid and the accessible-name prefix.

Author any glyphs needed in `src/components/icons/index.tsx` as inline SVG.

`src/components/Heatmap.test.tsx` asserts every item in the behavior block against the three fixtures, including the
sparse-beats-ramp-at-max case and the exactly-one-zero-tabindex case, and runs axe directly over each rendered
container with the contrast rule disabled and a comment recording that contrast is covered by the Lighthouse
accessibility category in plan 06-09.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/components/Heatmap.test.tsx` exits 0.
    - The rendered populated fixture contains exactly 168 gridcell-role elements and exactly one element with a zero tabindex — asserted in the test, not by grep.
    - `grep -c 'sparse-hatch' web/src/components/Heatmap.tsx` is at least 2 (defined once, referenced by cells).
    - `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/components/Heatmap.test.tsx</automated>
  </verify>
  <done>168 cells, one tab stop, a labelled six-entry legend, a texturally distinct sparse category that wins at every count, and no axe violations.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Pattern card, recent events and the assembled detail page</name>
  <files>web/src/components/PatternCard.tsx, web/src/components/PatternCard.test.tsx, web/src/components/RecentEvents.tsx, web/src/components/RecentEvents.test.tsx, web/src/app/restaurant/[slug]/page.tsx, web/src/app/restaurant/restaurant-page.test.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Component Inventory item 10 (the two mutually exclusive renderings and the omission contract), §Copywriting Contract → "Pattern sentence rules" (all seven) and → Empty states (the restaurant recent-events row), §State Contracts (the heatmap, PatternCard and recent-events rows), §Page Layout Contracts (the `/restaurant/[slug]` row and the meta-line format)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-114 (the whole page contract), D-108 (`pattern_status` embedding)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Common Pitfalls → Pitfall 8 (the ready-with-no-report fallback)
    - `docs/api.md` pattern and restaurant sections as written in 06-03
    - `web/src/components/{EmptyState,OfflineState}.tsx` and `web/src/components/ui/*` from 06-04 — the primitives this task composes
    - `web/src/lib/format.ts` from 06-04 — `relativeTime`, `slotLabel`, `partyLabel`, `metaLine`
  </read_first>
  <behavior>
    - With a ready report carrying two detected rules, the card renders `summary_text` as prose plus exactly two chips, each showing its rule name and, beneath it, its percentage, its sample size and its CI range.
    - With a ready report carrying one detected rule out of four possible, exactly one chip renders and none of the other three rule names appears anywhere in the rendered output.
    - With a collecting-data report, the card renders the exact quantified placeholder plus a progress hairline against 14 days, and renders zero chips.
    - With a ready status but a null report, the card renders the collecting-data placeholder rather than an empty card.
    - No chip renders a percentage without its sample size in the same chip.
    - `RecentEvents` with ten events renders ten rows using the documented row format; with zero events it renders the documented 'No tables have opened yet' heading and body.
    - The page renders exactly one h1; the meta line renders neighborhood, cuisine and price tier joined with a middle dot and carries no truncation class.
    - When the restaurant fetch returns null the page renders the documented not-found copy with a browse action; when the heatmap or pattern fetch returns null that surface alone renders the OfflineState band and the rest of the page still renders.
    - The assembled page produces zero axe violations with the contrast rule disabled.
  </behavior>
  <action>
`src/components/PatternCard.tsx`: two mutually exclusive renderings selected by `status`. The ready rendering prints
`summary_text` as prose constrained to the 65-character-measure width, then one neutral badge chip per entry in the
report's `rules` array, each with the rule's name and a muted label line carrying its percentage, its sample size and
its confidence-interval range in the documented format. The collecting-data rendering prints the exact placeholder
sentence and a thin hairline showing days-of-history against 14. There is no third rendering: a rule the model did
not detect gets no chip, no gray chip and no not-detected label — omission is the contract. Guard the ready-with-null
report case into the placeholder branch and comment that this is the Pitfall 8 fallback.

`src/components/RecentEvents.tsx`: an ordered list of the last ten openings using `src/lib/format.ts` for the
relative time, the party label and the slot label, with the documented empty state beneath a heading when the list is
empty. Row heights are fixed so a later append cannot shift the section below.

`src/app/restaurant/[slug]/page.tsx`: assemble the full page. Fetch the restaurant detail, the heatmap and the
pattern through `src/lib/api.ts`. Header: the cover image through the image component with the priority flag and a
meaningful alt naming the restaurant, the name as the single h1, the meta line built by `metaLine` and allowed to
wrap, the active-watch-count neutral badge, and the primary CTA. Body, in order: the heatmap card with its caption
naming both axes, the pattern card, and the recent-events list. Each surface independently selects its loading,
empty, error or offline rendering per the State Contracts table — a null from one fetch must not blank the others.
Use `pattern_status` from the restaurant response to choose the card's rendering without waiting on a second request,
and reconcile with the pattern response when it arrives.

`src/components/PatternCard.test.tsx` and `src/components/RecentEvents.test.tsx` assert their behavior items,
including a rendered-output scan proving that no undetected rule name appears and that no percentage appears without
its sample size. `src/app/restaurant/restaurant-page.test.tsx` renders the page shell with `vi.stubGlobal("fetch")`
over the typed fixtures for: the happy path, a null restaurant, a null heatmap, and a null pattern; asserts the
single h1 and the non-truncating meta line; and runs axe over the assembled output.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/components/PatternCard.test.tsx src/components/RecentEvents.test.tsx src/app/restaurant/restaurant-page.test.tsx` exits 0.
    - `grep -rc 'truncate' web/src/app/restaurant/\[slug\]/page.tsx` equals 0 (the meta line wraps).
    - `cd web && npm test` exits 0 (the whole frontend suite).
    - `cd web && npm run build && npm run typecheck && npm run lint` all exit 0.
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test && npm run typecheck && npm run lint</automated>
  </verify>
  <done>The restaurant page renders a heatmap, an honest pattern card and a recent-events list, degrades one surface at a time, and passes axe.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| API JSON → rendered SVG and prose | counts, `summary_text` and restaurant metadata arrive from the API and become user-visible claims |
| remote image host → image optimizer | `cover_photo_url` points at a third-party host |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-22 | Tampering | over-claiming a sparse heatmap cell | high | mitigate | `sparse` is server-computed (06-02) and the component honours it above the ramp at every count, proven by a test at `count === max`; the legend names the category and each cell's accessible name states it |
| T-06-23 | Tampering | XSS via `summary_text` or a restaurant name | high | mitigate | Both render as text nodes; the raw-HTML-prop gate from 06-04 covers the whole tree and this plan adds nothing that would need it |
| T-06-24 | Information disclosure | a booking token reaching the page | medium | mitigate | The pattern and heatmap payloads carry aggregate counts and prose only; the recent-events list renders date, time and party size — the page never requests a field carrying a token |
| T-06-25 | Denial of service | image optimizer abused as an open proxy | medium | mitigate | `images.remotePatterns` (06-04) declares explicit hostname and pathname; this page passes a URL from the API through that allowlist and does not widen it |
| T-06-26 | Repudiation | the detail page and the pattern route disagreeing about readiness | medium | mitigate | `pattern_status` comes from the same cached value as `/pattern` (06-03), and the card falls back to the placeholder on a ready-with-null report |
| T-06-SC | Tampering | npm installs | high | mitigate | This plan installs nothing — no chart library, no icon package. Recorded in the SUMMARY |
</threat_model>

<verification>
- `cd web && npm test && npm run typecheck && npm run lint && npm run build`
- `make web-build-offline` still exits 0 with the new route present
</verification>

<success_criteria>
- The heatmap renders 168 server-side SVG cells, one tab stop, a labelled six-entry legend and a sparse category that beats the ramp at every count.
- The pattern card renders only detected rules, always with sample size and CI, and falls back to the placeholder rather than rendering empty.
- `/restaurant/[slug]` has one h1, a wrapping meta line, a neutral watch-count badge and one accent CTA, and degrades surface by surface.
- axe reports zero violations on every rendered fixture.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-05-SUMMARY.md` when done.
Record whether the heatmap's arrow-key roving focus needed a scoped client island (and if so, exactly what it
contains), because D-114 and UI-SPEC A-8 promise a pure server component.
</output>
