---
phase: 06-pattern-intelligence-frontend-pwa
plan: 04
type: execute
wave: 4
depends_on: ["06-03"]
files_modified:
  - web/package.json
  - web/package-lock.json
  - web/tsconfig.json
  - web/eslint.config.mjs
  - web/next.config.ts
  - web/postcss.config.mjs
  - web/vitest.config.mts
  - web/vitest.setup.ts
  - web/.gitignore
  - web/README.md
  - web/src/app/sw.ts
  - web/src/app/page.tsx
  - web/src/app/layout.tsx
  - web/src/app/offline/page.tsx
  - web/src/app/globals.css
  - web/src/app/manifest.ts
  - web/src/lib/api.ts
  - web/src/lib/format.ts
  - web/src/test/fixtures/api.ts
  - web/src/lib/api.test.ts
  - web/src/lib/format.test.ts
  - web/src/lib/gates.test.ts
  - web/src/app/home-shell.test.tsx
  - web/src/components/ui/Button.tsx
  - web/src/components/ui/Card.tsx
  - web/src/components/ui/Field.tsx
  - web/src/components/ui/Badge.tsx
  - web/src/components/ui/Toast.tsx
  - web/src/components/EmptyState.tsx
  - web/src/components/OfflineState.tsx
  - web/src/components/primitives.test.tsx
  - web/public/icons/icon-192.png
  - web/public/icons/icon-512.png
  - web/public/icons/maskable-512.png
  - web/public/icons/apple-touch-icon.png
  - web/public/icons/badge-72.png
  - Makefile
autonomous: true
requirements: [FE-01, FE-07]

estimate:
  tokens: 105000
  raw_tokens: 105000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "FE-01 probe: `web/public/sw.js` exists after `npm run build` and its source contains a `push` event listener — a build that silently emits no service worker is a red test, not a green build (BC-1, RESEARCH Pitfall 1)."
    - "No build or dev script passes the Turbopack flag; a Vitest gate reads `web/package.json` and fails if it appears anywhere (D-109a, BC-1)."
    - "`make web-build-offline` runs `npm run build` with the API base URL pointed at an unreachable port and exits 0 — a Vercel deploy with no backend produces a green build and a calm offline page, not a red deploy (D-110a, BC-2, RESEARCH Pitfall 2)."
    - "`src/lib/api.ts :: safeFetch` never throws: network failure, DNS failure, timeout, 4xx and 5xx all resolve to a null/offline result so every server component renders a state instead of crashing the prerender (D-110a, BC-2)."
    - "Every read from a server component goes through `src/lib/api.ts`; a Vitest gate asserts no bare fetch call exists anywhere else under `web/src` (BC-2 warning sign)."
    - "The service worker's `push` handler wraps the ENTIRE async chain in `event.waitUntil(...)` and always supplies a non-empty notification body — the iOS subscription-revocation pitfall (D-117, RESEARCH Pitfall 3, STATE.md Phase 4 blocker)."
    - "`notificationclick` is typed against `NotificationEvent`; there is no `NotificationClickEvent` type and using it fails the type check (BC-8)."
    - "Service worker runtime caching: the API origin from the environment gets an explicit GET-only NetworkFirst rule with a 5-minute max age (Serwist's default `/api/` rule is same-origin only and would never match), the live feed stream is never cached, and the authenticated management and watch routes are never cached (D-117a, BC-4)."
    - "`/offline` and `/` are listed in `additionalPrecacheEntries` with a build-derived revision, because Serwist's generated precache manifest contains only build assets and no page shells (D-117a, BC-3)."
    - "`npm run lint` and `npm run typecheck` both exit 0 with the generated service worker excluded from both — the two commands lint different file sets and both are phase gates (BC-7, RESEARCH Pitfall 6)."
    - "`images.remotePatterns` is generated from the hostnames actually present in `scripts/seed/restaurants.yml` `cover_photo_url` values at execution time, each with an explicit hostname AND pathname (D-109b; an implicit wildcard pathname turns the image optimizer into an open proxy)."
    - "The manifest is served from a single typed route (`src/app/manifest.ts`) — exactly one manifest exists in the project, and it is also listed in the precache entries (D-117b, RESEARCH OQ-3)."
    - "Design tokens are declared as CSS custom properties on `:root`, overridden inside a `prefers-color-scheme: dark` media query, and mapped into Tailwind with `@theme inline` — plain `@theme` inlines the light value at build time and silently drops the dark override (UI-SPEC Design System)."
    - "Every interactive element in every primitive is at least 44x44 px (`min-h-11 min-w-11`) and carries a 2 px `--ring` `:focus-visible` outline at 2 px offset; a Vitest test asserts the classes on rendered output (FE-07, UI-SPEC Accessibility Contract)."
    - "Dark mode expresses elevation with a border, not a shadow, and the accent fill lightens while its text colour flips to `--accent-ink` — white text on the dark-mode accent would measure 2.6:1 (UI-SPEC Color)."
    - "Buttons are real `button` or `a` elements, never a div with a click handler; icon-only buttons carry an accessible name (UI-SPEC Component Inventory 1)."
    - "The `Field` error slot is always present in the DOM so validation never shifts layout, errors are announced as alerts and referenced by `aria-describedby`, and the control carries `aria-invalid` when invalid (UI-SPEC Component Inventory 3)."
    - "Notification-outcome badges are differentiated by text plus a glyph, never by unique hues — colour is never the only channel (UI-SPEC Component Inventory 4)."
    - "OfflineState renders two distinct causes with distinct copy: device offline versus backend unreachable while online. Collapsing them into one message is a defect because the user's remedy differs (UI-SPEC Component Inventory 12)."
    - "State-contract coverage (UI-SPEC): the loading, error and offline renderings for every data-bearing surface are supplied by these primitives — skeletons in the exact geometry of the real content, the documented error copy, and the `OfflineState` band."
  artifacts:
    - web/package.json
    - web/next.config.ts
    - web/tsconfig.json
    - web/eslint.config.mjs
    - web/vitest.config.mts
    - web/src/app/sw.ts
    - web/src/app/manifest.ts
    - web/src/app/globals.css
    - web/src/app/layout.tsx
    - web/src/app/offline/page.tsx
    - web/src/lib/api.ts
    - web/src/lib/format.ts
    - web/src/lib/gates.test.ts
    - web/src/components/ui/Button.tsx
    - web/src/components/ui/Card.tsx
    - web/src/components/ui/Field.tsx
    - web/src/components/ui/Badge.tsx
    - web/src/components/ui/Toast.tsx
    - web/src/components/EmptyState.tsx
    - web/src/components/OfflineState.tsx
    - Makefile
  key_links:
    - "`NEXT_PUBLIC_API_BASE_URL` is the only way the app finds the backend and is inlined at build time — a Vercel env change requires a redeploy, not a restart (D-110, BC-10)."
    - "`src/lib/api.ts` is typed against the `docs/api.md` route list recorded in the 06-03 SUMMARY; the `FeedEvent`, `Restaurant`, `HeatmapPayload`, `PatternReport`, `ManageBundle` and `GoVerdict` types are declared once here and imported everywhere."
    - "The service worker's API-origin cache rule reads the same `NEXT_PUBLIC_API_BASE_URL` value the api client does, so a mismatch is impossible."
    - "`web/src/app/globals.css` is the single definition site for every colour, radius, shadow, motion and spacing token in the UI-SPEC; components consume them as Tailwind utilities only."
  prohibitions:
    - "No script in `web/package.json` passes the Turbopack flag (Vitest gate over the file's text)."
    - "No bare fetch call exists under `web/src` outside `src/lib/api.ts` (Vitest gate scanning source with line comments stripped)."
    - "React's raw-HTML injection prop appears nowhere under `web/src` (Vitest gate; API-supplied strings such as `summary_text` and restaurant names are rendered as text)."
    - "`msw` is absent from `web/package.json` dependencies and devDependencies, and no test imports it — mocking is `vi.stubGlobal` over typed fixtures (D-118a)."
    - "The only `NEXT_PUBLIC_` names anywhere under `web/` are `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SITE_URL` and `NEXT_PUBLIC_VAPID_PUBLIC_KEY`; a private key name behind that prefix is a Vitest gate failure (RESEARCH Security V14)."
    - "The service worker never caches the live feed stream and never caches the management or watch endpoints."
    - "No theme toggle, no theme value in local storage, and no `dark` class strategy — dark mode is `prefers-color-scheme` only (UI-SPEC Design System)."
    - "No UI component library, no icon package and no chart library is installed; icons are inline SVG authored in-repo (D-109, UI-SPEC Registry Safety)."
    - "No type size outside 14 / 16 / 20 / 32 px and no font weight other than 400 and 600, with the single documented 11 px SVG axis-label exception (UI-SPEC Typography)."
  flagged_assumptions:
    - "UI-SPEC A-1..A-10 were resolved autonomously with no human present. A-3 (terracotta accent), A-4 (sparse cells get a hatch as well as gray), A-5 (heatmap cells exempt from the 44 px rule under WCAG 2.5.8 Essential), A-6 (the feed Pause toggle is mandatory) and A-8 (CSS-only heatmap tooltip) are the load-bearing ones. Each is cheap to overturn; a reviewer who disagrees should say so before the visual audit."
    - "Phase 5 response shapes were [ASSUMED] at planning time. The api client MUST be typed against the actual `docs/api.md` and `/openapi.json` snapshot recorded in the 06-03 SUMMARY; where a field name differs, change the type here and nowhere else (RESEARCH A5, A6)."
---

<!-- planner-discipline-allow: --turbopack -->
<!-- planner-discipline-allow: dangerouslySetInnerHTML -->
<!-- planner-discipline-allow: msw -->
<!-- planner-discipline-allow: await fetch( -->

<objective>
Stand up `web/` as a Next.js 15 PWA that builds green with no backend, emits a real service worker, and carries the
complete UI-SPEC design system.

Purpose: this is the frontend tracer. Every later frontend plan writes pages against these tokens, these primitives
and this api client. The three failure modes that only surface at build or deploy time — a silent missing service
worker, a prerender that dies because the API is down, and a lint pass that disagrees with the build — are all closed
here, in the first frontend commit.

Output: the `web/` project, its service worker, its design tokens, its five primitives, its typed api client, the
Makefile targets and the mechanical gates that keep all of it honest.
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
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-03-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| project | `web/` | Next.js 15.5.25, App Router, `src/` layout, TypeScript strict |
| route | `/` | minimal home shell in this plan; built out in 06-06 |
| route | `/offline` | service-worker document fallback |
| route | `/manifest.webmanifest` | emitted by `src/app/manifest.ts` |
| asset | `web/public/sw.js` | generated, git-ignored, lint-ignored |
| env vars | `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | the complete allowlist |
| lib function | `safeFetch<T>(path, init) -> Promise<T \| null>` | never throws |
| lib class | `ApiError` | mutations only; reads never throw |
| lib functions | typed api calls: restaurants, restaurant, heatmap, pattern, stats, feedRecent, manage, createWatch, patchWatch, deleteWatch, vapidPublicKey, pushSubscribe, goVerdict | one call site per route |
| lib functions | `src/lib/format.ts`: `relativeTime`, `slotLabel`, `partyLabel`, `priceTier`, `metaLine` | UI-SPEC copy formats |
| components | `ui/Button`, `ui/Card`, `ui/Field`, `ui/Badge`, `ui/Toast`, `EmptyState`, `OfflineState` | hand-rolled primitives |
| make targets | `web-install`, `web-dev`, `web-build`, `web-build-offline`, `web-test` | added to `.PHONY` with `##` doc comments |

<tasks>

<task type="tracer">
  <name>Task 1: Tracer — scaffold, service worker, api client, and a build that survives a dead backend</name>
  <files>web/package.json, web/tsconfig.json, web/eslint.config.mjs, web/next.config.ts, web/postcss.config.mjs, web/vitest.config.mts, web/vitest.setup.ts, web/.gitignore, web/README.md, web/src/app/sw.ts, web/src/app/page.tsx, web/src/app/offline/page.tsx, web/src/lib/api.ts, web/src/test/fixtures/api.ts, web/src/lib/api.test.ts, web/src/lib/gates.test.ts, web/src/app/home-shell.test.tsx, Makefile</files>
  <read_first>
    - `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/web/` — the executed scaffold: `package.json`, `next.config.ts`, `tsconfig.json`, `eslint.config.mjs`, `vitest.config.mts`, `vitest.setup.ts`, `src/app/sw.ts`, `src/lib/api.ts`, `src/app/offline/page.tsx`. These built green on this machine on 2026-09-05; copy them and apply the deltas below
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Blocking Corrections BC-1, BC-2, BC-3, BC-4, BC-7, BC-8, BC-9, BC-10; §Standard Stack (every pinned version and the exact install commands); §Architecture Patterns Patterns 5, 6, 7
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md` → "`web/` scaffold configs" and "`web/src/lib/api.ts`" — the config deltas, the corrected `safeFetch`, and the Makefile `.PHONY` + `##` convention
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-109, D-109a, D-109b, D-110, D-110a, D-117, D-117a, D-117b, D-118a
    - `docs/api.md` as it stands after 06-03, and the route list pasted into `06-03-SUMMARY.md` — the api client is typed against this, not against an assumption
    - `scripts/seed/restaurants.yml` — read the actual `cover_photo_url` hostnames for `images.remotePatterns`
    - `Makefile` — the `.PHONY` list and the `##` doc-comment convention `make help` parses
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Copywriting Contract → "Error and offline states" — the exact offline copy the tracer home renders
  </read_first>
  <action>
Scaffold with `npx create-next-app@15.5.25 web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --disable-git --yes`. The absence of the Turbopack flag is load-bearing: with it the build exits 0 and emits no
service worker at all. Then install `@serwist/next@9.5.12` as a dependency and `serwist@9.5.12` as a dev dependency,
followed by the dev toolchain at the pinned versions from RESEARCH §Standard Stack — `vitest@4.1.11`, `vite@8.2.2`,
`@vitejs/plugin-react@6.1.1`, `@testing-library/react@16.3.3`, `@testing-library/dom@10.4.1`,
`@testing-library/user-event@14.6.7`, `@testing-library/jest-dom@7.0.1`, `jsdom@30.0.1`, `axe-core@4.13.0`,
`lighthouse@13.4.1`, `chrome-launcher@1.2.1`. The initial dev install needs the legacy peer resolution flag once
(npm 10.9.2 crashes without it); document that one-time need in `web/README.md` and keep the flag out of the
`web-install` make target, which uses a clean install. Install NO mock-service-worker package: D-118a replaced it
with `vi.stubGlobal` over typed fixtures, which also removes the package-legitimacy concern the research raised.
Record the pinned version list and the legitimacy verdicts in the plan SUMMARY — there is no human available to gate
an install, so the audit is written down instead.

Config deltas from the scratch scaffold. `package.json` scripts are exactly `dev`, `build`, `start`, `lint`, `test`
(`vitest run`), `test:watch`, `typecheck` (`tsc --noEmit`) with no bundler flag on any of them. `tsconfig.json` adds
the webworker library, sets `types` to the Serwist typings package, and excludes the generated worker file from the
program. `eslint.config.mjs` ignores `node_modules`, `.next`, `out`, `build`, `next-env.d.ts` and the generated
worker globs; the same worker globs go into `web/.gitignore`. `vitest.config.mts` uses the React plugin, native
tsconfig-path resolution, the jsdom environment, `vitest.setup.ts` as a setup file, and an include glob over
`src/**/*.test.{ts,tsx}`; do not add the tsconfig-paths plugin, which Vite 8 warns is redundant. `vitest.setup.ts`
imports the jest-dom Vitest matchers and registers an afterEach cleanup. Do not enable global test APIs — import
`describe`/`it`/`expect` explicitly so the type check stays clean with a narrow `types` array.

`next.config.ts`: wrap the config with the Serwist initialiser using `src/app/sw.ts` as source and `public/sw.js` as
destination, navigation caching on, reload-on-online on, disabled in development, and `additionalPrecacheEntries`
listing `/offline`, `/` and `/manifest.webmanifest` each with a revision derived from the git HEAD (falling back to a
random id when git is unavailable) — the generated precache manifest carries only build assets, so page shells must
be named explicitly. Set `images.remotePatterns` from the hostnames actually present in the seed: run
`grep -oE 'cover_photo_url:[[:space:]]*https://[^[:space:]]+' scripts/seed/restaurants.yml | sed -E 's|.*https://||' | cut -d/ -f1 | sort -u`
and write one entry per host with an explicit protocol, hostname and pathname. Do not carry the research file's
placeholder host through, and do not omit the pathname.

`src/app/sw.ts`: copy the executed research worker. Keep its shape exactly. The API-origin rule is built from
`process.env.NEXT_PUBLIC_API_BASE_URL` and comes FIRST in the runtime-caching array, before the default cache list,
because Serwist's built-in API rule only matches same-origin requests and would never match this backend. Add an
explicit never-cache rule for the live feed path (a cached event stream never terminates and never updates) and
exclude the management and watch paths from every caching rule — those requests carry a bearer capability and must
not sit in a cache. The `push` listener wraps its entire async body in `event.waitUntil` and always passes a
non-empty body to `showNotification`; add the comment recording that a resolved-early handler or a bodyless
notification is what makes iOS revoke the subscription after roughly three sends. The click listener's event
parameter is typed as `NotificationEvent`. Set a document fallback to `/offline`.

`src/lib/api.ts`: the module every network read in the app goes through. Export `API_BASE` from
`NEXT_PUBLIC_API_BASE_URL` with a localhost default, an `ApiError` class carrying a status, and
`safeFetch<T>(path, init)` which returns `null` on a non-ok response and returns `null` from a caught exception —
it never throws, because an uncaught rejection inside a prerendered route fails the whole build. Then declare the
typed model interfaces and one function per route from the 06-03 route list: the restaurant list and detail, the
heatmap, the pattern, the stats counter, the recent-feed hydration, the manage bundle, the `/go` verdict, and the
mutation calls (create watch, patch watch, delete watch, push subscribe, vapid public key). Reads use `safeFetch`.
Mutations called from client islands MAY throw `ApiError`, because the rollback toast consumes it — say so in the
module docstring. Never set both a cache mode and a revalidate option on one call. Put every field-name mapping from
the API payload to the app's own types in this one module, so a Phase 5 shape difference is a one-file change.

`src/test/fixtures/api.ts`: typed fixture objects for each response shape, used by `vi.stubGlobal("fetch", ...)` in
tests. `src/lib/api.test.ts`: assert `safeFetch` resolves null for a rejected fetch, a 500, and a 404, and returns
the parsed body on 200; assert a mutation raises `ApiError` with the right status.

`src/app/offline/page.tsx` and a minimal `src/app/page.tsx`: the home shell fetches the stats counter through the api
client and, when the result is null, renders the exact backend-unreachable copy from the UI-SPEC error table with a
retry affordance. This is the tracer's observable outcome — a build with no backend produces a page a person can read.

`src/lib/gates.test.ts`: a Vitest module that reads project files from disk and asserts the mechanical prohibitions.
Read `web/package.json` as text and assert the bundler flag string is absent and that the mock-service-worker package
name is absent from both dependency maps. Walk `web/src/**/*.{ts,tsx}`, strip line comments before scanning, and
assert: no bare fetch call outside `src/lib/api.ts`; no occurrence of React's raw-HTML injection prop; and that every
`NEXT_PUBLIC_` identifier found belongs to the three-name allowlist. Include a guard-the-guard assertion that the
walked file list has more than five entries so a path typo cannot make the gate vacuous. Strip comments before
scanning so an explanatory comment can neither satisfy nor break a gate.

Makefile: add `web-install` (clean install in `web/`), `web-dev`, `web-build`, `web-build-offline` (build with the
API base URL pointed at an unreachable loopback port), and `web-test` — each in `.PHONY` and each with a `##` doc
comment or it disappears from `make help`. Above `web-build-offline`, write the multi-line rationale comment in the
style of the existing `test:` target: this target is the standing regression test for the prerender-with-no-backend
failure, and it is what makes a Vercel deploy without a backend a green deploy.
  </action>
  <acceptance_criteria>
    - `make web-build-offline` exits 0.
    - `cd web && npm run build && test -f public/sw.js` exits 0, and `grep -c '"push"' web/public/sw.js` is at least 1.
    - `cd web && npm test` exits 0 with `src/lib/gates.test.ts`, `src/lib/api.test.ts` and `src/app/home-shell.test.tsx` all passing.
    - `cd web && npm run lint` exits 0 and `cd web && npm run typecheck` exits 0.
    - `grep -c 'placeholder.mise.place' web/next.config.ts` is at least 1, and every `remotePatterns` entry declares a `pathname`: `grep -c 'pathname' web/next.config.ts` equals the number of `hostname` occurrences.
    - `make help` lists `web-install`, `web-dev`, `web-build`, `web-build-offline` and `web-test`.
    - `node -e "const p=require('./web/package.json');process.exit(p.dependencies?.msw||p.devDependencies?.msw?1:0)"` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>make web-build-offline && cd web && npm test && npm run lint && npm run typecheck</automated>
  </verify>
  <done>`web/` builds green against a dead backend, emits a service worker with a push handler, renders a readable offline home, and the four mechanical gates are enforced by tests.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Design tokens, root layout shell, manifest and the copy formatters</name>
  <files>web/src/app/globals.css, web/src/app/layout.tsx, web/src/app/manifest.ts, web/public/icons/icon-192.png, web/public/icons/icon-512.png, web/public/icons/maskable-512.png, web/public/icons/apple-touch-icon.png, web/public/icons/badge-72.png, web/src/lib/format.ts, web/src/lib/format.test.ts</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Design System (the `@theme inline` token-wiring block and why plain `@theme` fails), §Spacing Scale, §Typography, §Color (both schemes, every measured ratio), §Radii & Elevation, §Motion (including the reduced-motion block), §Accessibility Contract → Focus and Other (skip link, landmarks, single h1, `lang`)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Copywriting Contract → "Live feed row format" — the exact relative-time, slot-time and party-size formats `format.ts` implements
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Architecture Patterns → Pattern 7 (the typed manifest route and the head tags it emits)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-109 (one variable font), D-111 (mobile-first, 44 px, focus rings, reduced motion, contrast), D-117 (manifest fields), D-117b (manifest as a typed route)
    - `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/web/src/app/{layout.tsx,manifest.ts,globals.css}` — the executed shapes
  </read_first>
  <behavior>
    - `relativeTime` returns `Just now` under 60 seconds, `N min ago` from 1 to 59 minutes, and `N hr ago` at 60 minutes and above.
    - `slotLabel` renders a slot in America/New_York as a weekday abbreviation plus 12-hour time with minutes and an uppercase meridiem.
    - `partyLabel` renders `Table for 1` and `Table for 2` — the noun never pluralises.
    - `priceTier(3)` renders three dollar signs; `metaLine` joins neighborhood, cuisine and price tier with a middle dot and returns a string that wraps rather than truncates.
    - `relativeTime` at exactly 60 seconds returns `1 min ago` and at exactly 3600 seconds returns `1 hr ago` (the boundary is inclusive at the upper unit).
    - Every formatter is pure and takes an explicit reference time — no formatter reads the clock itself.
  </behavior>
  <action>
`src/app/globals.css`: declare every UI-SPEC token as a CSS custom property on `:root` using the light values from
the Color table, override the full set inside a `prefers-color-scheme: dark` media query with the dark values, then
map each one into Tailwind's theme with `@theme inline` referencing the custom property. The `inline` keyword is
load-bearing — plain `@theme` resolves the value at build time and the media-query override is silently dropped. Add
the radius scale, the two elevation levels (with the note that dark mode uses a border in place of the card shadow),
the three motion tokens, a `.tnum` utility applying tabular figures, and the global reduced-motion block from the
UI-SPEC verbatim. Keep Tailwind v4's default spacing base so the 44 px tap target is `min-h-11` with no config file.

`src/app/layout.tsx`: load Inter Variable through the Next font helper with swap display, the latin subset and a
`--font-sans` variable, self-hosted so there is no third-party font request and no swap-induced layout shift against
the LCP budget. Set `lang` on the html element. Emit the viewport meta with `viewport-fit=cover` and the theme
colour, and link the manifest through the metadata API. Render, in DOM order: a visually-hidden-until-focused skip
link targeting the main landmark, a header containing a nav landmark with a main label, a main landmark with the
skip-link target id, a footer, and the single persistent polite live region the Toast primitive portals into.
Exactly one h1 per page is a page-level responsibility; the layout must not render one.

`src/app/manifest.ts`: the typed manifest route with the app name and short name, the 192, 512 and maskable-512
icons, the apple touch icon, standalone display and the theme colour. This is the ONLY manifest in the project —
do not also create a static one. Generate the five PNG icons in `web/public/icons/` from a simple in-repo mark; they
must be real files at their declared sizes because the iOS Add-to-Home-Screen flow reads them.

`src/lib/format.ts`: the pure copy formatters listed in the behavior block, each taking an explicit `now` or
reference value. `src/lib/format.test.ts` asserts every item in that block including both boundaries.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/lib/format.test.ts` exits 0.
    - `grep -c '@theme inline' web/src/app/globals.css` equals 1 and `grep -c 'prefers-color-scheme: dark' web/src/app/globals.css` is at least 1.
    - `grep -c 'prefers-reduced-motion' web/src/app/globals.css` is at least 1.
    - `grep -cE '^\s*--(accent-ink|border-strong|ring|skeleton|shadow-overlay|motion-feed)' web/src/app/globals.css` is at least 6 (the full token set landed, not a subset).
    - `ls web/public/icons/ | wc -l` is at least 5 and `find web/public -name 'manifest.webmanifest' | wc -l` equals 0 (the manifest is the typed route only).
    - `cd web && npm run build && npm run lint && npm run typecheck` all exit 0.
    - `grep -rc 'localStorage' web/src/app/layout.tsx` equals 0 (no theme persistence).
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/lib/format.test.ts && npm run typecheck</automated>
  </verify>
  <done>Every UI-SPEC token exists once, in both schemes, mapped into Tailwind; the layout carries its landmarks, skip link and live region; the manifest is a single typed route; and the copy formatters are pinned at their boundaries.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The seven hand-rolled primitives and their accessibility gates</name>
  <files>web/src/components/ui/Button.tsx, web/src/components/ui/Card.tsx, web/src/components/ui/Field.tsx, web/src/components/ui/Badge.tsx, web/src/components/ui/Toast.tsx, web/src/components/EmptyState.tsx, web/src/components/OfflineState.tsx, web/src/components/primitives.test.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Component Inventory items 1 through 5, 11 and 12 — every variant, size, state and accessibility requirement, verbatim
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Accessibility Contract → Focus, Forms, Dialogs; §Copywriting Contract → Buttons (the complete label list), Empty states, Error and offline states
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §State Contracts — the loading/empty/error/offline rendering each surface expects from these primitives
    - `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/web/src/components/Heatmap.test.tsx` — the direct axe-core test idiom (no wrapper package), including disabling the contrast rule in jsdom
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Code Examples → "axe in a component test" — and the note that contrast is covered by Lighthouse, not by axe in jsdom
    - `web/src/app/globals.css` as written in Task 2 — the token names these components consume
  </read_first>
  <behavior>
    - Every `Button` variant renders a real button element, carries `min-h-11` and `min-w-11`, and renders a focus-visible ring class; an icon-only button without an accessible name fails the test.
    - `Button` in its pending state sets `aria-busy` and keeps its rest-state width so the layout does not jump.
    - `Card` renders its border in both schemes and does not become interactive by default.
    - `Field` always renders its error slot element even when there is no error; when invalid it sets `aria-invalid`, renders the error with an alert role, and references it via `aria-describedby`.
    - `Field` renders a real label element bound to its control — a placeholder alone is a test failure.
    - `Badge` renders each notification outcome as text plus a glyph with the neutral fill; no outcome gets a unique hue.
    - `Toast` renders into a polite live region, auto-dismisses only when it has no action, and pauses its timer on hover and focus-within.
    - `EmptyState` renders a heading, a body and an optional action; every empty state used in this phase names a next action or expectation.
    - `OfflineState` renders the device-offline copy and the backend-unreachable copy as two distinct messages selected by cause, each with a retry affordance.
    - Rendering each primitive produces zero axe violations (with the contrast rule disabled, because jsdom resolves no custom properties).
  </behavior>
  <action>
Author the seven primitives to the UI-SPEC inventory exactly. Each is a server component unless the spec marks it a
client island — only `Toast` is. Consume tokens as Tailwind utilities mapped from `globals.css`; no component
declares a raw colour value.

`Button` carries the four variants and the two sizes from the spec, with the hover, focus-visible, active, disabled
and pending states as described. There is no small size, because a control below 44 px violates the phase's tap
target requirement. The disabled treatment uses the aria attribute rather than the native attribute in the one case
where the control must stay focusable.

`Card` composes an optional header slot with an optional trailing badge, a body and an optional footer, with the
responsive padding from the spacing table. A whole-card link is one tab stop, achieved with a single anchor over the
title plus an overlay pseudo-element — not several nested links.

`Field` composes label, optional helper text, control and a permanently-present error slot, with the rest, focus,
invalid and disabled states from the spec. The focus ring is an outline, and the border colour does NOT change on
focus, so a focused-and-invalid field still reads as invalid.

`Badge` defaults to neutral and adds the accent-outline variant used only for the sample-data label and the hatched
variant used only for the heatmap legend. Notification outcomes render as neutral badges differentiated by text plus
a small inline SVG glyph — a check for delivered, clicked and still-available, a slash for gone. Do not introduce a
palette of outcome colours.

`Toast` is the only client island here: bottom-anchored with the safe-area inset on mobile, bottom-right above the
small breakpoint, a maximum of three stacked with the oldest removed first, auto-dismissing at six seconds only when
it has no action, and pausing its timer on hover and focus-within. It portals into the layout's persistent live
region; rollback and error toasts announce assertively. Note in the module docstring that a toast is never the only
place an error appears.

`EmptyState` and `OfflineState` share a centred stack shape but differ in semantics: the offline variant sits on a
sunken background band so it reads as a system condition, carries a retry button, and selects between two distinct
copy sets by cause. Collapsing device-offline and backend-unreachable into one message is a defect, because the
remedies differ; take both copy sets verbatim from the UI-SPEC error table.

Author every inline SVG glyph these components need under `src/components/icons/` as small typed components. Install
no icon package.

`src/components/primitives.test.tsx` asserts every item in the behavior block. Include a rendered-output tap-target
sweep: render one instance of every interactive primitive and assert each rendered interactive element carries both
44 px minimum classes. Run axe directly against each rendered container and assert the violation id list is empty,
with the contrast rule disabled and a comment recording that contrast is verified by the Lighthouse accessibility
category in plan 06-09 rather than here — jsdom computes no layout and resolves no custom properties, so an axe
contrast result here would be a false claim.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/components/primitives.test.tsx` exits 0.
    - `grep -rc 'min-h-11' web/src/components/ui/ | grep -vc ':0'` shows every interactive primitive file carries the class.
    - `grep -rcE '#[0-9A-Fa-f]{6}' web/src/components/ | grep -v 'icons/' | grep -c ':[1-9]'` equals 0 (no raw hex outside the icon set).
    - `grep -rc 'focus-visible' web/src/components/ui/Button.tsx web/src/components/ui/Field.tsx` is at least 1 for each.
    - `cd web && npm run build && npm run lint && npm run typecheck` all exit 0.
    - `cd web && npm test` exits 0 (the whole frontend suite, including the Task 1 gates).
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test && npm run lint && npm run typecheck</automated>
  </verify>
  <done>Seven primitives exist to the UI-SPEC contract, every interactive element clears 44 px with a visible focus ring, no state is conveyed by colour alone, and axe finds nothing.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| API responses → rendered DOM | restaurant names, `summary_text` and error bodies arrive from the API and are rendered to users |
| build environment → client bundle | `NEXT_PUBLIC_*` values are inlined into JavaScript every visitor downloads |
| npm registry → build | 20-plus third-party packages enter the build with no human to approve them |
| service worker cache → subsequent requests | anything cached is replayed to the user, possibly across sessions |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-16 | Tampering | XSS via API-supplied strings | high | mitigate | React escapes by default and the Task 1 gate proves React's raw-HTML injection prop appears nowhere under `web/src`; `summary_text` and restaurant names render as text nodes |
| T-06-17 | Information disclosure | a secret behind a public env prefix | critical | mitigate | The Task 1 gate allowlists exactly three `NEXT_PUBLIC_` names; the VAPID private key name can never appear because it is not on the list. BC-10 note in `web/README.md` records that these values are inlined into the bundle |
| T-06-18 | Information disclosure | bearer tokens in the service-worker cache | high | mitigate | The worker's runtime rules cache unauthenticated GETs only; management and watch paths are excluded, and the live feed stream is never cached |
| T-06-19 | Denial of service | third-party image host used as an open proxy | medium | mitigate | `images.remotePatterns` entries declare an explicit hostname AND pathname, generated from the seed's actual hosts — never an implicit wildcard |
| T-06-20 | Spoofing | a build with no service worker ships and push silently never fires | high | mitigate | The Turbopack flag is gated out of `package.json` by a test, and the build verification asserts the generated worker exists and contains a push listener |
| T-06-21 | Denial of service | prerender crash on an unreachable API | high | mitigate | `safeFetch` never throws, the bare-fetch gate keeps every read inside it, and `make web-build-offline` is a standing regression test |
| T-06-SC | Tampering | npm installs with no human approver | high | mitigate | Every package is pinned to the exact version the research installed and exercised; the mock-service-worker package flagged by the legitimacy audit is NOT installed (D-118a removed the need for it); the full pinned list and each verdict is written into `06-04-SUMMARY.md` in place of the checkpoint a human would otherwise gate |
</threat_model>

<verification>
- `make web-build-offline` — the BC-2 regression gate
- `cd web && npm test && npm run typecheck && npm run lint && npm run build`
- `test -f web/public/sw.js && grep -c '"push"' web/public/sw.js`
- `make help` lists all five new web targets
</verification>

<success_criteria>
- `web/` builds green with an unreachable backend and renders a readable offline state.
- `public/sw.js` is emitted on every build and contains a push listener wrapped in a waitUntil chain.
- Lint, type check, build and tests are all green, and the four mechanical gates (no bundler flag, no bare fetch, no raw-HTML prop, env allowlist) are enforced by a test rather than by discipline.
- Every UI-SPEC token exists in both schemes via `@theme inline`, and the seven primitives clear 44 px, focus rings, label binding and axe.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-04-SUMMARY.md` when done.
It MUST contain the package legitimacy audit in place of the human checkpoint: every installed package with its
pinned version and the research verdict, an explicit statement that no mock-service-worker package was installed,
and the hostnames actually written into `images.remotePatterns` with the command that produced them.
</output>
