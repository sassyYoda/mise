---
phase: 03-resy-playwright-fleet
plan: 04
type: execute
wave: 2
depends_on: [03-02]
files_modified:
  - Makefile
  - tests/conftest.py
  - tests/fakes/__init__.py
  - tests/fakes/resy_stub.py
  - services/poller/sources/resy/fingerprints.py
  - services/poller/sources/resy/stealth.py
  - tests/unit/test_browser_guard.py
  - tests/unit/test_fingerprints.py
  - tests/unit/test_stealth_script_names.py
  - tests/integration/test_stealth_applied.py
autonomous: true
requirements: [POLL-04]

estimate:
  tokens: 62000
  raw_tokens: 62000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`uv run playwright install chromium` has been run and `make browsers` re-runs it idempotently; the pinned revision named in `playwright/driver/package/browsers.json` is present on disk (D-71a, research B-1 — the pre-existing cache held the wrong revision and every launch failed)."
    - "`_chromium_available()` compares the INSTALLED directory against the revision the pinned `playwright` declares, honours `PLAYWRIGHT_BROWSERS_PATH` when set, and returns False for a mismatched revision — a directory glob would have reported the stale `chromium-1223` as available while every launch raised (D-71a, research A7)."
    - "A real headless Chromium context created from fingerprint row 0 and navigated to the in-process stub origin reports `navigator.webdriver` as undefined/None, a `navigator.userAgent` exactly equal to that row's UA, `navigator.platform` / `languages` / `hardwareConcurrency` / `deviceMemory` / WebGL vendor+renderer all matching the same row, an EMPTY `pageerror` collector, and the same properties on a page created afterwards in that context (D-60a, research B-2/B-3/Pattern 4)."
    - "The stealth assertion navigates to the stub origin and never to `about:blank`, where `navigator_user_agent` throws and silently disables every later patch including `webdriver` (research §Pitfall 3)."
    - "`FINGERPRINTS` holds at least 6 unique rows; every row is internally coherent (UA OS token, `platform`, `sec-ch-ua-platform`, `Accept-Language` first tag and WebGL vendor agree) and no row's UA or `sec-ch-ua` contains a headless marker (research B-9, §Pitfall 2)."
    - "Every name in `SCRIPT_ORDER` exists in `playwright_stealth.core._stealth_config.SCRIPTS`; the package is untyped so `mypy` cannot catch a key typo and only this unit test can (research §Pitfall 7)."
    - "The stub serves `GET /4/find` from the Resy fixtures and switches behaviour through `POST /__ctl/mode` across `normal`, `rate_limited`, `banned_empty`, `challenge_403` and `error_500`, recording every request's headers in a hit log readable at `GET /__ctl/hits` (D-71)."
  artifacts:
    - tests/fakes/resy_stub.py
    - services/poller/sources/resy/fingerprints.py
    - services/poller/sources/resy/stealth.py
    - tests/unit/test_browser_guard.py
    - tests/unit/test_fingerprints.py
    - tests/unit/test_stealth_script_names.py
    - tests/integration/test_stealth_applied.py
  key_links:
    - "`build_init_script(fp)` -> `BrowserContext.add_init_script` — installed once per context, never per page; the library's own `stealth_async(page)` is per-page and would leave sibling pages with `navigator.webdriver === true` (research B-2)."
    - "`Fingerprint.sec_ch_ua` / `.sec_ch_ua_platform` / `.accept_language` -> `new_context(extra_http_headers=...)` (03-05) — `APIRequestContext` emits none of these by itself, so POLL-04's 'realistic request headers' is satisfied here or nowhere (research B-9)."
    - "`stub_base` fixture -> `RESY_API_BASE` -> `ResyAdapter` (03-05) and the soak script (03-07) — one fake serves every browser test in the phase, and no test ever reaches a `resy.com` host."
  prohibitions:
    - "MUST NOT delete, move, repair, or 'clean up' browser binaries, caches, or any other artifact this project did not install — the shared `ms-playwright` cache holds another tool's browsers, and reclaiming their disk is not this project's decision to make."
---

<objective>
Stand up the browser test harness — the correct Chromium revision, a revision-aware guard, and an
in-process Resy fake — and build the two pure modules the fleet's identity depends on: a coherent
fingerprint table and a stealth init script built from OUR fingerprint rather than the library's
random one.

Purpose: research reproduced that `tf-playwright-stealth` as shipped overwrites a macOS Chrome 140
context with a Linux Chrome 96 identity while the HTTP `User-Agent` still says macOS — applying it
would make the fleet MORE detectable than doing nothing. This plan replaces that with a verified
per-context recipe and proves it against a real origin.
Output: `make browsers`, a revision-comparing guard, `tests/fakes/resy_stub.py`, `fingerprints.py`,
`stealth.py`, and the integration test that proves the patch actually applied.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/03-resy-playwright-fleet/03-CONTEXT.md
@.planning/phases/03-resy-playwright-fleet/03-PATTERNS.md
</context>

<tasks>

<task type="tracer">
  <name>Task 1: End-to-end tracer — installed Chromium, guarded, hits an in-process stub through a stealthed context</name>
  <precondition>The machine can reach `cdn.playwright.dev` to download ~253 MB of browser binaries; `uv run playwright --version` reports 1.58.0.</precondition>
  <files>Makefile, tests/conftest.py, tests/fakes/__init__.py, tests/fakes/resy_stub.py, services/poller/sources/resy/fingerprints.py, services/poller/sources/resy/stealth.py, tests/integration/test_stealth_applied.py</files>
  <read_first>
    - tests/conftest.py lines 1-49 (the `_docker_available()` guard idiom and the module-scoped container fixtures the new fixtures sit beside)
    - Makefile lines 1-12 and 50-54 (the exhaustive `.PHONY` line and the `## description` convention `help` greps for)
    - services/poller/sources/resy/fixtures.py (written in 03-01 — the bodies the stub serves)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-1 (the wrong-revision failure and the exact guard code), §B-2, §B-3 (the library's random incoherent fingerprint, and the dead `StealthConfig` fields), §Pattern 4, §Pitfall 2 (the headless UA leak and `channel="chromium"`), §Pitfall 3 (the `about:blank` silent failure), §Pitfall 8 (`pytest_asyncio.fixture` vs `pytest.fixture` for module scope; function scope is recommended), §Pitfall 9 (uvicorn signal handling is already safe — do not add the dead workaround), §Code Examples "Chromium availability guard", "`ContextPool` browser lifecycle", "Coherent per-context stealth", "In-process uvicorn stub"
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-60, §D-60a, §D-71, §D-71a
  </read_first>
  <action>
Run `uv run playwright install chromium` as an explicit, reviewable step — research reproduced that
the cache on this machine held revision 1223 while the pinned `playwright==1.58.0` requires 1208, so
every `chromium.launch()` failed. Add a `browsers:` target to the `Makefile` running exactly that
command with a `##` description, and add `browsers` to the exhaustive `.PHONY` line. Note in the
target's description that this downloads browser executables from a CDN.

Add to `tests/conftest.py`, beside the existing Docker guard: `_chromium_available()` which reads the
revision from `Path(playwright.__file__).parent / "driver/package/browsers.json"`, resolves the
browser root from `PLAYWRIGHT_BROWSERS_PATH` when set and otherwise the per-platform default, and
returns whether `chromium-{revision}` exists. A glob-based check must not be used: it would find the
stale sibling revision and report available while every launch raises. Add a function-scoped
`browser` fixture that starts `async_playwright()`, launches with `headless=True, channel="chromium"`
(the headless shell leaks `HeadlessChrome` in client hints), yields, and in `finally` does
`await asyncio.shield(browser.close())` followed by `await pw.stop()` — a bare `await` in a `finally`
reached through cancellation re-raises immediately and leaks six OS processes. Skip with the message
`Playwright Chromium for the pinned playwright version is not installed — run \`make browsers\``.

Create `tests/fakes/__init__.py` and `tests/fakes/resy_stub.py`: a FastAPI app serving
`GET /4/find` from the 03-01 fixtures, whose response depends on a module-level mode set by
`POST /__ctl/mode` — `normal` (the success body), `rate_limited` (429 + a `Retry-After` header),
`banned_empty` (200 with an empty `venues` list), `challenge_403` (403 with the HTML challenge body
and a `text/html` content type), `error_500` (500, plain text). Record every inbound request's path,
query parameters and full header mapping into an in-memory hit log exposed by `GET /__ctl/hits`, and
clear it via `DELETE /__ctl/hits`. Add a `stub_base` fixture in the same module (or in
`tests/conftest.py`) that binds an ephemeral port, runs `uvicorn.Server.serve()` as a task, waits for
`server.started` under `asyncio.wait_for`, yields the base URL, and shuts down with
`server.should_exit = True` plus a bounded `wait_for` — never by cancelling the serve task. Do not
add the `install_signal_handlers = lambda: None` workaround; it has no effect in the pinned uvicorn
and signal handling is already restored correctly.

Write `services/poller/sources/resy/fingerprints.py`: a frozen dataclass `Fingerprint` and a
module-level `FINGERPRINTS: tuple[Fingerprint, ...]` of at least 6 rows, plus
`fingerprint_for_index(i: int) -> Fingerprint` doing round-robin selection (not `random.choice` —
rotation is per context, and a per-request random UA on a cookie-bearing session is itself a signal).
Each row carries everything both the browser and the wire need to agree on: `user_agent`, `viewport`,
`locale`, `timezone_id`, `device_scale_factor`, `platform`, `languages`, `accept_language`,
`sec_ch_ua`, `sec_ch_ua_platform`, `brands`, `hardware_concurrency`, `device_memory`, `webgl_vendor`,
`webgl_renderer`. Rows must be internally coherent — a macOS UA pairs with `MacIntel`, `"macOS"`, an
Apple WebGL vendor and a plausible core count; an inconsistent triple is a harder signal than none.
No row may contain a headless marker.

Write `services/poller/sources/resy/stealth.py`: `SCRIPT_ORDER` (the verified 16-name tuple),
`stealth_opts(fp) -> dict[str, Any]` building the `opts` object the shipped JS reads entirely from
the passed fingerprint, and `build_init_script(fp) -> str` joining `const opts = {json}` with the
scripts from `playwright_stealth.core._stealth_config.SCRIPTS` in that order. Do NOT call
`stealth_async` and do NOT set fingerprint values through `StealthConfig`: research proved the former
is per-page and randomises the identity, and that the latter's `vendor` / `renderer` /
`nav_user_agent` / `nav_platform` / `languages` / `nav_vendor` fields are read by nothing in 1.2.0.
State both facts in the module docstring so a future reader does not "fix" it back.

Write `tests/integration/test_stealth_applied.py` as the tracer: with the `browser` and `stub_base`
fixtures, create ONE context from `FINGERPRINTS[0]` with `user_agent=`, `viewport=`, `locale=`,
`timezone_id=`, `device_scale_factor=` and the `extra_http_headers` triple, install
`build_init_script(fp)` via `add_init_script`, open a page, attach a `pageerror` collector, navigate
to the stub origin, and assert every property in `must_haves.truths` — plus that the collector stayed
empty, and that a SECOND page created afterwards in the same context reports the same values. Add an
explicit negative case asserting the suite never navigates to `about:blank` for these assertions.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_stealth_applied.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run playwright install chromium` exits 0 and `make browsers` re-runs it idempotently.
    - `uv run python -c "import sys; sys.path.insert(0,'tests'); from conftest import _chromium_available; print(_chromium_available())"` prints `True`.
    - `uv run pytest tests/integration/test_stealth_applied.py -q -p no:cacheprovider` exits 0 in under 20 seconds.
    - `make help` lists a `browsers` target and `grep -c "^\.PHONY.*browsers" Makefile` returns 1.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0 with no `type: ignore` added for `playwright`.
  </acceptance_criteria>
  <done>A real Chromium context, built from our own fingerprint and patched once at the context level, reports a coherent non-automated identity against a live local origin, with zero page errors.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Fingerprint coherence and stealth script-name invariants at the unit tier</name>
  <files>tests/unit/test_fingerprints.py, tests/unit/test_stealth_script_names.py, services/poller/sources/resy/fingerprints.py</files>
  <read_first>
    - services/poller/sources/resy/fingerprints.py and stealth.py (as written in Task 1)
    - tests/unit/test_ua_rotation.py (the 31-line data-invariant template: count, uniqueness, per-row assertions)
    - services/poller/config.py lines 22-40 (`USER_AGENTS` and its invariant comment — the precedent for a data table with a documented contract)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-3 (the incoherence that motivates every assertion here), §B-9 (why each row needs a matching `sec-ch-ua` / `sec-ch-ua-platform` / `Accept-Language` triple), §Pitfall 2, §Pitfall 7 (`playwright_stealth` is untyped, so a `SCRIPTS` key typo needs a test not a type)
  </read_first>
  <behavior>
    - `len(FINGERPRINTS) >= 6` and every `user_agent` value is distinct.
    - For each row: the OS token in the UA, `platform`, `sec_ch_ua_platform` and the WebGL vendor family agree; `accept_language`'s first tag equals `languages[0]`; `sec_ch_ua` names the same major browser version as the UA; `hardware_concurrency` and `device_memory` are plausible integers.
    - No row's `user_agent` or `sec_ch_ua` contains a headless marker (asserted case-insensitively).
    - `fingerprint_for_index` is round-robin: indices `0..2*len-1` visit every row exactly twice in order, and index `len` returns the same row as index `0`.
    - Every name in `SCRIPT_ORDER` is a key of `SCRIPTS`; `SCRIPT_ORDER` has no duplicates; `utils` precedes every script that depends on it, and `navigator_user_agent` precedes `webdriver` in the order actually shipped.
    - `build_init_script(FINGERPRINTS[0])` is a non-empty string containing the row's UA and parsing as valid JS only insofar as the `opts` prefix is valid JSON (assert the JSON segment round-trips through `json.loads`).
  </behavior>
  <action>
Write `tests/unit/test_fingerprints.py` and `tests/unit/test_stealth_script_names.py` covering every
row in `<behavior>` as parametrised per-fingerprint tests, so a failure names the offending row
rather than "the table". Derive the OS/browser tokens with small explicit helpers in the test file —
not by importing a helper from the module under test, which would make the assertion circular.

If any assertion exposes an incoherent row, fix the ROW in `services/poller/sources/resy/fingerprints.py`
rather than relaxing the assertion, and add a one-line comment above `FINGERPRINTS` stating the
contract the tests enforce (the `USER_AGENTS` invariant comment is the precedent).
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_fingerprints.py tests/unit/test_stealth_script_names.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_fingerprints.py tests/unit/test_stealth_script_names.py -q` exits 0.
    - `uv run python -c "from services.poller.sources.resy.fingerprints import FINGERPRINTS as f; print(len(f), len({x.user_agent for x in f}))"` prints two equal numbers, both at least 6.
    - `uv run python -c "from services.poller.sources.resy.stealth import SCRIPT_ORDER; from playwright_stealth.core._stealth_config import SCRIPTS; print(sorted(set(SCRIPT_ORDER) - set(SCRIPTS)))"` prints `[]`.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>Fingerprint coherence and the stealth script-name contract are pinned at the unit tier, so they are re-checked on every commit without a browser.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The browser guard is itself tested, and the stub's control surface is pinned</name>
  <files>tests/unit/test_browser_guard.py, tests/fakes/resy_stub.py</files>
  <read_first>
    - tests/conftest.py (the `_chromium_available()` written in Task 1)
    - tests/fakes/resy_stub.py (written in Task 1)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-1 (the exact failure a glob-based guard would hide) and §Assumptions Log A7 (`PLAYWRIGHT_BROWSERS_PATH` breaks a hard-coded root)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Code Examples "The `/4/find` call and its error taxonomy" (the five observed stub modes with their exact statuses, content types and body lengths)
    - tests/unit/test_confirm_delay_is_not_configurable.py (the single-property guard test style)
  </read_first>
  <behavior>
    - Pointed at a temp directory containing `chromium-{pinned_revision}`, the guard returns True.
    - Pointed at a temp directory containing only `chromium-{pinned_revision + 15}`, the guard returns False — this is the exact stale-sibling case a glob would have passed.
    - Pointed at an empty temp directory, the guard returns False.
    - With `PLAYWRIGHT_BROWSERS_PATH` set to a temp directory, the guard reads that root rather than the per-platform default.
    - The guard never raises, even when the manifest path is unreadable — it returns False so the suite skips with a message instead of erroring at collection.
    - Driven through a plain in-process client (no browser), the stub returns status 200/429/200/403/500 and content types `application/json`/`application/json`/`application/json`/`text/html`/`text/plain` for modes `normal`/`rate_limited`/`banned_empty`/`challenge_403`/`error_500`, and the hit log records one entry per request with its full header mapping.
  </behavior>
  <action>
Write `tests/unit/test_browser_guard.py` driving `_chromium_available()` through `monkeypatch` over
`PLAYWRIGHT_BROWSERS_PATH` and `tmp_path`, covering every row in `<behavior>`. Read the pinned
revision from the same manifest the guard reads, so the test cannot drift from the installed
playwright on a future bump. Include the unreadable-manifest case, asserting the guard returns False
rather than propagating.

Add a stub self-test to the same file (or a sibling test module co-located with the fake) driving
`tests/fakes/resy_stub.py` through FastAPI's in-process test client — no browser, no port, no
network — asserting the five-mode matrix and the hit-log contract in `<behavior>`. This keeps the
stub's own correctness at the unit tier, so a browser test that fails is unambiguously about the
browser.

If any assertion exposes a guard that resolves the root incorrectly or a stub mode whose content type
does not match the observed real responses, fix the implementation rather than the assertion.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_browser_guard.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_browser_guard.py -q` exits 0 and runs in under 3 seconds (no browser, no container).
    - `uv run pytest tests/unit -q` exits 0.
    - `grep -c "def test_" tests/unit/test_browser_guard.py` returns at least 6.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>The guard that decides whether nine browser tests run is itself proven against the stale-revision case, and the stub's five modes are pinned without a browser.</done>
</task>

</tasks>

## Artifacts this phase produces (plan 04)

| Kind | Symbol / path | Notes |
|------|---------------|-------|
| make target | `make browsers` | `uv run playwright install chromium` |
| test helper | `tests/conftest.py :: _chromium_available()` | revision-aware, honours `PLAYWRIGHT_BROWSERS_PATH` |
| fixture | `tests/conftest.py :: browser` | function-scoped; `channel="chromium"`; shielded `finally` |
| fixture | `stub_base` | in-process uvicorn on an ephemeral port |
| package | `tests/fakes/` | new test-fake package |
| module | `tests/fakes/resy_stub.py` | FastAPI app |
| route | `GET /4/find` | fixture-backed availability |
| route | `POST /__ctl/mode` | `normal` \| `rate_limited` \| `banned_empty` \| `challenge_403` \| `error_500` |
| route | `GET /__ctl/hits`, `DELETE /__ctl/hits` | per-request header/query log |
| module | `services/poller/sources/resy/fingerprints.py` | |
| dataclass | `Fingerprint` | frozen; UA, viewport, locale, timezone_id, device_scale_factor, platform, languages, accept_language, sec_ch_ua, sec_ch_ua_platform, brands, hardware_concurrency, device_memory, webgl_vendor, webgl_renderer |
| constant | `FINGERPRINTS: tuple[Fingerprint, ...]` | >= 6 coherent rows |
| function | `fingerprint_for_index(i) -> Fingerprint` | round-robin |
| module | `services/poller/sources/resy/stealth.py` | |
| constant | `SCRIPT_ORDER: tuple[str, ...]` | 16 verified `SCRIPTS` keys |
| function | `stealth_opts(fp) -> dict[str, Any]` | built from OUR fingerprint |
| function | `build_init_script(fp) -> str` | installed once per context |
| test | `tests/integration/test_stealth_applied.py` | stub origin, never `about:blank` |
| test | `tests/unit/test_fingerprints.py`, `test_stealth_script_names.py`, `test_browser_guard.py` | |

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `cdn.playwright.dev` -> local filesystem | ~253 MB of executable content is downloaded and then run |
| Chromium context -> the polled origin | The context's advertised identity is what a bot-detection system evaluates |
| shipped `playwright_stealth` JS -> our page context | Third-party JavaScript is executed in every page of every context |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-03-15 | Spoofing (failed) | `stealth.py` + `fingerprints.py` | high | mitigate | `stealth_async` is never called; `opts` is built from our own coherent row, so the fleet cannot advertise a Linux Chrome 96 identity over a macOS Chrome 140 UA (research B-3). Coherence is unit-tested per row |
| T-03-16 | Information Disclosure | headless markers | medium | mitigate | `channel="chromium"` plus a mandatory explicit `user_agent=` on every context, and a unit assertion that no fingerprint row carries a headless marker (research §Pitfall 2) |
| T-03-17 | Tampering | `uv run playwright install chromium` | high | mitigate | Made an explicit, reviewable `make browsers` target rather than an implicit side effect of a test run; the guard verifies the installed directory matches the revision the pinned package declares, so a substituted or stale build is detected (ASVS V14) |
| T-03-18 | Denial of Service | leaked browser processes | high | mitigate | The shared `browser` fixture closes under `asyncio.shield` in `finally`; research reproduced six surviving processes without it |
| T-03-19 | Repudiation | test traffic | high | mitigate | Every browser test targets the in-process stub on `127.0.0.1`; no test resolves or contacts a `resy.com` host |
| T-03-SC | Tampering | npm/pip/cargo installs | low | accept | No new packages. The one non-package supply-chain item — the browser download — is gated as `make browsers` and revision-verified (research §Package Legitimacy Audit) |
</threat_model>

## Flagged assumptions (probe, unresolved — review manually)

None in this plan.

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration/test_stealth_applied.py -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/` exits 0.
- `make help` lists `browsers`.
</verification>

<success_criteria>
- The correct Chromium revision is installed and re-installable with one make target.
- A stealthed context reports a coherent, non-automated identity on a real origin, with a second page confirming per-context (not per-page) application.
- Fingerprint coherence and the stealth script-name contract fail loudly at the unit tier.
- An in-process Resy fake serves all five observed response modes with a header hit log.
</success_criteria>

<output>
Create `.planning/phases/03-resy-playwright-fleet/03-04-SUMMARY.md` when done.
</output>
</content>
