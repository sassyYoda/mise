---
phase: 04-notification-pipeline
plan: 05
type: execute
wave: 3
depends_on: [04-01, 04-03]
files_modified:
  - services/notifier/config.py
  - services/notifier/templates.py
  - services/notifier/pattern_hook.py
  - services/notifier/providers/__init__.py
  - services/notifier/providers/base.py
  - services/notifier/providers/email.py
  - services/notifier/providers/sms.py
  - services/notifier/providers/push.py
  - shared/metrics.py
  - tests/unit/gsm7.py
  - tests/unit/test_templates_sms_length.py
  - tests/unit/test_provider_email.py
  - tests/unit/test_provider_sms.py
  - tests/unit/test_provider_push.py
  - tests/unit/test_push_revocation.py
  - tests/unit/test_retry_policy.py
  - tests/unit/test_no_sync_sdk_imports.py
autonomous: true
requirements: [NOTIF-03, NOTIF-04, NOTIF-05]

estimate:
  tokens: 72000
  raw_tokens: 72000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "All three providers issue their HTTP calls through the process-wide `shared.http_client.get_async_client()` singleton, injected at construction; no provider constructs an `httpx.AsyncClient`, and no module under `services/` or `shared/` imports the Resend, Twilio or pywebpush SDK or a synchronous HTTP client — `tests/unit/test_no_sync_sdk_imports.py` is a non-vacuous source gate over both trees (D-78, BC-1, CLAUDE.md async-only)."
    - "`EmailProvider.send` POSTs to `{RESEND_API_BASE}/emails` with `Authorization: Bearer`, a JSON body carrying `from`/`to`/`subject`/`html`/`text`/`headers`, the RFC 8058 pair `List-Unsubscribe` (an HTTPS URI) and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` inside `headers`, and an `Idempotency-Key` equal to the deterministic `job_id`; a 200 yields `ProviderResult(provider_id=<id>, status_code=200)` (D-78, D-76a, NOTIF-03)."
    - "`SmsProvider.send` POSTs form-encoded to `{TWILIO_API_BASE}/2010-04-01/Accounts/{sid}/Messages.json` with HTTP Basic auth, `MessagingServiceSid`, `Body`, `To` and a `StatusCallback` pointing at the API's Twilio status route; a 201 yields `ProviderResult(provider_id=<sid>, …)`, and the sid is the SC2 duplicate oracle (D-78, NOTIF-04)."
    - "`PushProvider.send` encrypts with `http_ece.encrypt(..., version='aes128gcm')` and signs with `py_vapid.Vapid.from_string(...).sign(claims)`; `pywebpush` is never imported from a service module. The `aud` claim is the per-endpoint push-service ORIGIN derived with `urlsplit`, `exp` is `now + 12 h` (never the library default of exactly 24 h, which Apple rejects), `sub` is `VAPID_SUBJECT`, and the request carries `Content-Encoding: aes128gcm`, `Content-Type: application/octet-stream`, `TTL: 60` and `Urgency: high` (D-78a/BC-1, NOTIF-05)."
    - "The encrypted body round-trips: a test subscription generated with a real P-256 keypair decrypts the emitted payload back to the original JSON with `http_ece.decrypt`, and the signed header's `k=` value equals `VAPID_PUBLIC_KEY`, so a mismatched keypair fails at unit-test time rather than as a production 403."
    - "PROBE NOTIF-04/encoding: the SMS body's length is measured in GSM 03.38 SEPTETS, not characters. `render_sms` emits only GSM-7 characters — ASCII hyphen, never an em dash, en dash, middot or curly apostrophe, each of which forces UCS-2 and drops the single-segment limit from 160 to 70 — and the body is at most 160 septets for EVERY one of the 55 seeded restaurant names with a 10-digit `notification_log.id`, computing the link from the configured `PUBLIC_BASE_URL` host rather than a literal (D-81a/BC-2)."
    - "PROBE NOTIF-04/empty: `render_sms` is total — an empty or whitespace-only restaurant name, a `seat_type` of `None`, an absent estimated-window text and an empty `time_slot` each render a well-formed body rather than raising or emitting a dangling separator; and the name is hard-truncated so the body is bounded BY CONSTRUCTION rather than by the happy-path input being short."
    - "PROBE NOTIF-05/unclassified — flagged assumption: iOS revokes a subscription after roughly three pushes whose payload lacks a usable notification. The service worker is Phase 6, so this phase's obligations are sender-side and are asserted here: the push payload ALWAYS carries a non-empty `title` and a non-empty `body`, the whole JSON stays well under 4096 bytes, and 404/410 sets `revoked_at` (research §Pitfall 10)."
    - "PROBE NOTIF-03/unclassified — flagged assumption: Resend's error body schema is unpublished. Every retry decision keys off the HTTP STATUS, never the body; the body is parsed defensively as `{statusCode, name, message}` for log detail only, and a 409 is treated as ALREADY SENT — not retried, not dead-lettered (research A4, §Resend error table)."
    - "Retry policy per D-79: email 3 attempts with exponential 1-8 s backoff, SMS 2 attempts, push 2 attempts; retryable is 429 plus 5xx plus `httpx.TransportError`/`ReadTimeout`, and every other 4xx is definitive. A `Retry-After` header — in delta-seconds OR HTTP-date form — is honoured through the tenacity wait and CLAMPED to `MAX_RETRY_AFTER_SECONDS`; an unparseable value is treated as absent."
    - "Push 404 and 410 are NOT dead letters: both mark `push_subscriptions.revoked_at`, raise a typed revocation signal for the worker's email fallback, and record `error='subscription_revoked'` (D-79)."
    - "`NOTIFY_DRY_RUN=true` short-circuits every provider before any network call, returning `ProviderResult(provider_id='dry-run-<job_id>')`, and a channel whose credentials are absent is never constructed — a job for it records `error='provider_unconfigured'` instead of raising (D-80)."
    - "`shared/metrics.py` gains `notification_latency_seconds` (Histogram, label `channel`, explicit buckets straddling 5 s, 10 s and 60 s) and `notifications_total` (Counter, labels `channel`, `status`) at ONE definition site; importing the module twice in one process raises nothing, and a test reads the counter through the exposed sample name `notifications_total` while expecting the metric FAMILY name `notifications` (D-86, research §Prometheus naming gotcha)."
  artifacts:
    - services/notifier/templates.py
    - services/notifier/providers/base.py
    - services/notifier/providers/email.py
    - services/notifier/providers/sms.py
    - services/notifier/providers/push.py
    - tests/unit/gsm7.py
    - tests/unit/test_templates_sms_length.py
    - tests/unit/test_provider_email.py
    - tests/unit/test_provider_sms.py
    - tests/unit/test_provider_push.py
    - tests/unit/test_push_revocation.py
    - tests/unit/test_no_sync_sdk_imports.py
  key_links:
    - "`shared.links.go_link_sms()` (04-01) -> `render_sms()` -> the 160-septet budget. Seven septets of headroom at the worst seeded name; anything added to the token payload or the host name spends them."
    - "`make_job_id()` (04-02) -> the Resend `Idempotency-Key` header. Provider-side 24 h dedupe whose window matches the Layer-2 TTL exactly, closing the one gap Redis cannot: a crash after the request left the process but before the response was read."
    - "`http_ece.encrypt` + `py_vapid.sign` -> the push body and its `Authorization` header. Importing the reference SDK instead would drag a synchronous HTTP stack into the service and make the async-only gate nominal rather than honest (BC-1)."
    - "`shared/metrics.py` single definition site -> every importer. A second definition of either metric raises `Duplicated timeseries` at import and takes the notifier down at start (Pitfall 8)."
    - "`MAX_RETRY_AFTER_SECONDS` -> the consumer's head-of-line latency. `max_poll_records=1` plus an unclamped provider-supplied delay parks the whole pipeline and eventually trips a Kafka rebalance (Pitfall 5)."
  prohibitions:
    - "MUST NOT import a vendor notification SDK or a synchronous HTTP client from any module under `services/` or `shared/`; the reference implementations may be imported from `tests/` as cross-check oracles only."
    - "MUST NOT construct an `httpx.AsyncClient` anywhere outside `shared/http_client.py`; providers receive the client at construction."
    - "MUST NOT emit a character outside the GSM 03.38 basic table into an SMS body, and MUST NOT measure that body with `len()`."
    - "MUST NOT log a rendered message body, a recipient address or phone number, an `Authorization` header, an API key, or a subscription endpoint; failures are logged by shape."
    - "MUST NOT wait with a bare `asyncio.sleep` or `time.sleep` in `services/notifier/`; backoff is delegated to `tenacity`, whose own sleep lives inside its package."
    - "MUST NOT honour an unclamped provider-supplied `Retry-After`."
    - "MUST NOT re-declare a metric that `shared/metrics.py` already defines."
    - "MUST NOT send a push payload with an empty `title` or an empty `body`."
---

<objective>
Build the message renderers and the three async provider clients: Resend over JSON, Twilio over
form-encoded Basic auth, and Web Push over RFC 8188 `aes128gcm` with a VAPID JWT — all through the
shared `httpx` client, none through a vendor SDK, all with an explicit retry policy and a clamped
`Retry-After`.

Purpose: this is where the phase touches three third-party contracts and one payload-encryption
standard, and where a wrong implementation produces a SILENT drop rather than an exception — a push
the browser discards with no error anywhere, an SMS that costs three segments because of one em dash,
a retry storm that parks the consumer for an hour. Every one of those is pinned here by a test that
can fail.
Output: `services/notifier/templates.py`, four provider modules, the two Prometheus metrics, and seven
unit test files including the GSM-7 septet helper and the SDK-import gate.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/04-notification-pipeline/04-CONTEXT.md
@.planning/phases/04-notification-pipeline/04-PATTERNS.md
@.planning/phases/04-notification-pipeline/04-01-SUMMARY.md
@.planning/phases/04-notification-pipeline/04-03-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — one rendered alert email leaves through the shared client and increments the counter</name>
  <files>services/notifier/config.py, services/notifier/templates.py, services/notifier/providers/__init__.py, services/notifier/providers/base.py, services/notifier/providers/email.py, shared/metrics.py, tests/unit/test_provider_email.py</files>
  <precondition>`shared/metrics.py` exists, created by Phase 3 plan 03-02 with its single-definition-site rule and its `tests/unit/test_metrics_registry.py` double-import regression test. This task APPENDS two metrics to that module; a second definition of an existing metric raises `Duplicated timeseries in CollectorRegistry` at import and takes the process down. If the module is absent, Phase 3 has not landed — stop and report the ordering violation rather than creating it fresh.</precondition>
  <read_first>
    - shared/http_client.py in full (the singleton, `LIMITS`, `TIMEOUT`, and the "do NOT construct one anywhere else" rule)
    - services/poller/sources/opentable/adapter.py (the injected-client provider shape: `__init__(self, client)`, the request construction and the error typing)
    - shared/metrics.py as created by Phase 3 (the definition-site header comment and the existing metric declarations)
    - tests/unit/test_metrics_registry.py (the double-import assertion and the `get_sample_value` sample-name convention)
    - shared/links.py and shared/tokens.py as written in 04-01
    - services/notifier/config.py as written in 04-03 (the lazy-accessor register to extend with the provider settings)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Resend" (the full request contract, the documented error table with its retry column, and the `Idempotency-Key` recommendation), §"Prometheus naming gotcha", §"Retries (tenacity 9.1.4)" (the verified transcript, the `wait_retry_after` shape and the clamp)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"One-click unsubscribe (RFC 8058)" (the two headers and the DKIM note)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-78, §D-79, §D-80, §D-81, §D-86, §D-76a
  </read_first>
  <behavior>
    - `render_email(ctx)` returns a subject naming the restaurant and the slot, an HTML body containing the restaurant, date, time, party size, a "Book now" anchor whose href is the `/go` URL and an unsubscribe footer link, a plain-text alternative carrying the same facts, and a headers mapping with the two RFC 8058 keys.
    - When `estimate_window_text` returns `None` the estimated-window line is OMITTED entirely rather than rendered empty.
    - `EmailProvider.send` against a respx-mocked route produces exactly one request, to the configured base URL, with a Bearer authorization header, a JSON content type, an `Idempotency-Key` equal to the job id, and the two unsubscribe headers nested inside the body's `headers` object.
    - A 200 response yields `ProviderResult` whose `provider_id` is the response `id`.
    - A 409 is treated as already-sent: no retry, no dead letter, and a result flagged as a duplicate.
    - A 422 is definitive: exactly one request is made.
    - A 500 followed by a 200 succeeds after exactly two requests; three 500s exhaust and raise a typed retryable exhaustion.
    - A 429 carrying `Retry-After: 1` is retried once and the wait is at most `MAX_RETRY_AFTER_SECONDS`.
    - `notifications_total` with labels `channel="email", status="sent"` increments by one per successful send, and `shared.metrics` imports twice in one interpreter without raising.
    - With `NOTIFY_DRY_RUN=true`, `send` makes zero requests and returns a `dry-run-` prefixed provider id.
  </behavior>
  <action>
Extend `services/notifier/config.py` with the provider settings, all lazy: `resend_api_key()`,
`resend_api_base()` (default `https://api.resend.com`), `notify_from_email()`, `twilio_account_sid()`,
`twilio_auth_token()`, `twilio_messaging_service_sid()`, `twilio_api_base()` (default
`https://api.twilio.com`), `twilio_status_callback_url()`, `vapid_private_key()`,
`vapid_public_key()`, `vapid_subject()`. Every base URL is env-overridable precisely so a test can
point `respx` at it. Add `email_enabled()` / `sms_enabled()` / `push_enabled()` returning whether the
channel's credentials are all present (D-80).

Write `services/notifier/templates.py` using `string.Template` and no new dependency (D-81). Define a
frozen `TemplateContext` carrying `restaurant_name`, `service_date`, `time_slot`, `party_size`,
`seat_type`, `go_url`, `go_link_sms`, `unsubscribe_url` and `estimated_window_text: str | None`, and
`render_email(ctx) -> EmailBody` returning `subject`, `html`, `text` and `headers`. The headers
mapping carries `List-Unsubscribe: <{unsubscribe_url}>` — an HTTPS URI, which RFC 8058 requires — and
`List-Unsubscribe-Post: List-Unsubscribe=One-Click`; note in the docstring that Resend signs the
verified domain's DKIM over the headers it is given, so passing them through the API's `headers` field
is what puts them in the signed set. Omit the estimated-window line entirely when
`estimated_window_text` is `None` rather than rendering an empty one; a misleading estimate is worse
than none.

Write `services/notifier/providers/__init__.py` and `services/notifier/providers/base.py`.
`base.py` owns the shared vocabulary: a frozen `ProviderResult(provider_id, status_code,
already_sent=False)`; a `ProviderError(status_code, code, retryable, retry_after)` exception carrying
enough to decide a retry without re-reading a response; `MAX_RETRY_AFTER_SECONDS = 30`;
`parse_retry_after(value) -> float | None` handling BOTH the delta-seconds and the HTTP-date forms and
returning `None` for anything unparseable; and `send_with_retry(fn, *, attempts, channel)` wrapping a
`tenacity.AsyncRetrying` whose `wait` prefers the pending exception's `retry_after` clamped to
`MAX_RETRY_AFTER_SECONDS` and otherwise falls back to exponential 1-8 s. Write the clamp's reason into
the code: an unclamped `Retry-After: 3600` parks a `max_poll_records=1` consumer for an hour, blows
the PERF-01 budget and eventually trips a Kafka rebalance. `send_with_retry` also increments
`notifications_total` and observes `notification_latency_seconds`, so no provider has to remember to.

Write `services/notifier/providers/email.py`. `EmailProvider(client)` takes the shared
`httpx.AsyncClient` at construction — never builds one. `send(to, subject, html, text, headers,
idempotency_key)` POSTs to `{resend_api_base()}/emails` with `Authorization: Bearer
{resend_api_key()}`, a JSON body of `from`/`to`/`subject`/`html`/`text`/`headers`, and an
`Idempotency-Key` request header equal to the job id. Map responses per the research error table:
200 succeeds; 409 returns `already_sent=True` without retry or dead letter; 429 with
`rate_limit_exceeded` and every 5xx is retryable; every other 4xx is definitive. Key those decisions
off the HTTP STATUS and never off the body — the error body schema is unpublished — while still
parsing the body defensively for log detail. Honour `dry_run()` by short-circuiting before the request
and returning a `dry-run-{job_id}` provider id.

Append to `shared/metrics.py`, at its single definition site, `notification_latency_seconds` (a
Histogram labelled `channel`, with explicit buckets straddling all three SLOs — 5 s push, 10 s SMS,
60 s overall — so Grafana can read each off one histogram) and `notifications_total` (a Counter
labelled `channel` and `status`). Add a comment recording the naming gotcha: the exposed SAMPLE is
`notifications_total` while the metric FAMILY is `notifications`, and a companion
`notifications_created` gauge is emitted, so a family-name collision check and any
`REGISTRY.collect()` assertion must expect `notifications`.

Write `tests/unit/test_provider_email.py` covering every bullet in `<behavior>` with `respx` pointed
at the configured base URL, using `route.call_count` as the request-count oracle, and asserting the
metric through `get_sample_value("notifications_total", {...})`.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_provider_email.py tests/unit/test_metrics_registry.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_provider_email.py tests/unit/test_metrics_registry.py -q` exits 0.
    - `uv run python -c "import shared.metrics as m; print(m.notification_latency_seconds._name, m.notifications_total._name)"` prints `notification_latency_seconds notifications`.
    - `uv run python -c "import importlib; importlib.import_module('shared.metrics'); importlib.reload(importlib.import_module('shared.metrics')); print('ok')"` prints `ok`.
    - `uv run python -c "import inspect, services.notifier.providers.email as e; print(len(inspect.signature(e.EmailProvider.__init__).parameters))"` prints `2` — the client is injected, not constructed.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One rendered alert email travels the whole provider path — template, shared client, mocked Resend, retry wrapper, metric — and its request shape, idempotency header, unsubscribe headers and error mapping are each pinned by a test.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The SMS provider and the GSM-7 septet budget</name>
  <files>services/notifier/providers/sms.py, services/notifier/pattern_hook.py, tests/unit/gsm7.py, tests/unit/test_templates_sms_length.py, tests/unit/test_provider_sms.py</files>
  <read_first>
    - services/notifier/templates.py and services/notifier/providers/base.py as written in Task 1
    - shared/crypto.py (`decrypt_phone`, `canonical_e164`) as written in 04-01
    - shared/links.py (`go_link_sms`, `public_host`) as written in 04-01
    - scripts/seed/restaurants.yml (all 55 seeded names — the test iterates every one of them)
    - services/state_machine/parsers/__init__.py (the registry-stub shape `pattern_hook.py` mirrors)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Blocking Corrections" BC-2 in full (both defects, the measured 163/153-septet results, the three corrections and the two guards) and §"SMS Length Budget (measured)" (the GSM 03.38 basic and extension tables and the reference `gsm7_septets` implementation)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Twilio" (the request contract, the 201 response fields, the `status` vocabulary and the 1600-char Body note)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-78, §D-79, §D-81, §D-81a
  </read_first>
  <behavior>
    - `gsm7_septets` returns 1 per basic-table character, 2 per extension-table character, and `None` for any character outside both tables.
    - For every one of the 55 seeded restaurant names, `render_sms` with a 10-digit `notification_log.id` yields a body that is GSM-7 representable and at most 160 septets.
    - The rendered body contains the restaurant name, a compact date, a compact time, the party size, the scheme-less `/go` link and the STOP instruction.
    - The body contains an ASCII hyphen and none of the em dash, en dash, middot or curly apostrophe.
    - A pathologically long restaurant name is hard-truncated so the body still fits — the bound holds by construction, not by luck.
    - The link is derived from the configured `PUBLIC_BASE_URL` host, so raising the host length raises the measured septet count in the test.
    - An empty or whitespace-only name, a `None` `seat_type` and an empty `time_slot` each produce a well-formed body with no dangling separator.
    - `SmsProvider.send` against a respx-mocked route issues one form-encoded POST to the configured Twilio path with Basic auth, `MessagingServiceSid`, `To`, `Body` and `StatusCallback`; a 201 yields a `ProviderResult` whose `provider_id` is the response `sid`.
    - A 429 with `Retry-After` is retried once and no more (2 attempts total); a 400 is definitive with exactly one request.
    - A phone blob that fails to decrypt produces `error='phone_decrypt_failed'` and no request, and the exception's text never reaches the log.
    - `estimate_window_text(source, restaurant_id)` returns `None` for every input in this phase.
  </behavior>
  <action>
Write `tests/unit/gsm7.py` with the GSM 03.38 basic and extension tables and `gsm7_septets(s) -> int |
None` exactly as the research reference implements it, plus a module docstring stating the point: the
single-segment limit is 160 SEPTETS, one character outside the tables forces UCS-2 and drops the limit
to 70, and `len()` is off by up to 2.3x. This is a test helper, not production code, and it lives in
`tests/unit/` so the assertion is independent of the renderer it checks.

Write `services/notifier/pattern_hook.py` in the shape of `services/state_machine/parsers/__init__.py`:
`estimate_window_text(source: str, restaurant_id: int) -> str | None` returning `None`, with a
docstring stating that Phase 6 PATTERN-03 implements it, that returning `None` means the templates
OMIT the line rather than render an empty one, and that a misleading estimate is worse than no
estimate (D-81).

Add `render_sms(ctx) -> str` to `services/notifier/templates.py`. Shape:
`"{name} {m/d} {h:mm}{AM|PM} x{party} - {host}/go/{token} Reply STOP to opt out"`. Three constraints
are load-bearing and each gets a comment naming BC-2: only ASCII punctuation, because a single
non-GSM-7 character halves the segment; no URL scheme, because every mobile client autolinks a bare
host and the eight characters are the difference between fitting and not; and a hard truncation of the
restaurant name computed from a module constant `SMS_MAX_SEPTETS = 160` so the body is bounded by
construction. Record the measured headroom in the docstring — 153 septets at the longest seeded name,
158 at a 10-digit id — so the next person to add a word to this template knows exactly what they are
spending.

Write `services/notifier/providers/sms.py`. `SmsProvider(client)` takes the shared client.
`send(to_e164, body, status_callback, job_id)` POSTs form-encoded (httpx `data=` produces the right
content type) to `{twilio_api_base()}/2010-04-01/Accounts/{sid}/Messages.json` with HTTP Basic auth,
`To`, `MessagingServiceSid`, `Body` and `StatusCallback`. Decrypt the recipient inside this module and
nowhere else — that is the only place a plaintext number exists (D-85, WATCH-05) — catching
`cryptography.exceptions.InvalidTag` BY TYPE and recording `error='phone_decrypt_failed'` without
letting the exception's text near a log line. Map 201 to success taking `sid` as the provider id; 2
attempts with the shared retry wrapper; 429 and 5xx retryable, every other 4xx definitive.
Short-circuit on `dry_run()`.

Write `tests/unit/test_templates_sms_length.py` iterating EVERY name parsed from
`scripts/seed/restaurants.yml` — the test loads the YAML rather than hard-coding a list, so a future
name containing an accented character fails loudly in CI — asserting GSM-7 representability and the
160-septet bound at a 10-digit id, plus the truncation, the punctuation and the empty-input cases.
Add an explicit assertion that the parsed name list is non-empty and has at least 50 entries, so a
YAML path change cannot make the loop vacuous. Write `tests/unit/test_provider_sms.py` for the request
shape, the retry counts and the decrypt-failure path.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_templates_sms_length.py tests/unit/test_provider_sms.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_templates_sms_length.py tests/unit/test_provider_sms.py -q` exits 0.
    - `uv run pytest tests/unit/test_templates_sms_length.py --collect-only -q` reports at least 55 collected cases.
    - `uv run python -c "from tests.unit.gsm7 import gsm7_septets as g; print(g('a-b'), g('a{b'), g('a—b'))"` prints `3 4 None`.
    - `uv run python -c "import services.notifier.pattern_hook as p; print(p.estimate_window_text('opentable', 42))"` prints `None`.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Every seeded restaurant name renders an SMS that fits one GSM-7 segment with a full-length signed link, the bound holds by construction for any name, and the Twilio request shape, retry count and decrypt-failure path are pinned.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Web Push over `http_ece` + `py_vapid`, subscription revocation, and the SDK-import gate</name>
  <files>services/notifier/providers/push.py, tests/unit/test_provider_push.py, tests/unit/test_push_revocation.py, tests/unit/test_retry_policy.py, tests/unit/test_no_sync_sdk_imports.py</files>
  <read_first>
    - services/notifier/providers/base.py as written in Task 1
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Blocking Corrections" BC-1 in full (the module-import transcript, the reference implementation's own imports, and the proven-equivalent 217-byte round trip)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Web Push — VAPID + aes128gcm" (the exact `http_ece.encrypt` call, the header set, the claim rules, the status-code table and the per-origin header caching)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Code Examples" — "Web Push send (no pywebpush, no requests)"
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Pitfall 1" (the key-generation vs signing distinction that makes the Phase-1 STATE.md note inapplicable), §"Pitfall 2" (per-endpoint `aud`, the 24 h `exp` default), §"Pitfall 7" (respx list-valued lookups are unhashable — pass a tuple), §"Pitfall 10" (iOS revocation and the sender-side obligations)
    - tests/unit/test_no_inline_sleep.py and tests/unit/test_no_setnx_expire_pairs.py (the non-vacuity and comment-stripping idioms every new gate copies)
    - tests/integration/conftest.py `fake_push_subscription` as written in 04-02
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-78, §D-78a, §D-79
  </read_first>
  <behavior>
    - The emitted body decrypts back to the original payload JSON with the subscription's private key, proving the ECDH and record framing are right.
    - The request carries `Content-Encoding: aes128gcm`, `Content-Type: application/octet-stream`, `TTL: 60`, `Urgency: high` and a `vapid t=…,k=…` authorization header.
    - The header's `k=` value equals the configured `VAPID_PUBLIC_KEY`, so a mismatched keypair fails here rather than as a production 403.
    - The JWT's `aud` equals the push-service origin derived from the subscription endpoint — three different endpoints produce three different `aud` values from one process.
    - The JWT's `exp` is at most 12 hours ahead and is explicitly set, never left to the library default.
    - The payload JSON always carries a non-empty `title` and a non-empty `body`, and the whole body stays well under 4096 bytes; a context that would render an empty body raises before any request.
    - A 201 yields a `ProviderResult` whose `provider_id` comes from the `Location` header when present.
    - 404 and 410 both set `push_subscriptions.revoked_at`, raise the typed revocation signal, and produce `error='subscription_revoked'` — neither is dead-lettered.
    - 400, 403 and 413 are definitive with exactly one request; 429 and 5xx retry to a total of 2 attempts.
    - The signed header is cached per push-service origin and reused within its validity window rather than re-signed per message.
    - No module under `services/` or `shared/` imports a vendor notification SDK or a synchronous HTTP client, and the gate's scanned-file set is asserted non-empty and named.
  </behavior>
  <action>
Write `services/notifier/providers/push.py` (D-78a, BC-1). `PushProvider(client)` takes the shared
client. `send(subscription, payload, job_id)`:

Encrypt with `http_ece.encrypt(data, salt=None, private_key=<ephemeral P-256 from cryptography>,
dh=<subscription p256dh raw bytes>, auth_secret=<subscription auth raw bytes>, version="aes128gcm")`.
Under `mypy --strict`, `http_ece.encrypt` is untyped, so bind the result to an annotated local
(`encrypted: bytes = ...`) rather than returning it directly, or strict mode reports returning `Any`.
Sign with `py_vapid.Vapid.from_string(private_key=vapid_private_key()).sign(claims)` where
`aud = f"{scheme}://{netloc}"` from `urlsplit(subscription.endpoint)` — the library neither derives
nor validates it, and one cached header reused across Chrome, Firefox and Safari endpoints gets 401s
from the non-matching services — `exp = now + 12 * 3600` passed EXPLICITLY, because the default is
exactly `now + 86400` and "more than one day ahead" is a documented Apple rejection, and
`sub = vapid_subject()`, which is required and must be a `mailto:` or `https:` value.

Put the BC-1 reasoning in the module docstring: the reference SDK's `encode` for this content
encoding is a thin wrapper around the identical `http_ece.encrypt` call, so this is not a
reimplementation — it is the same call without dragging a synchronous HTTP stack into an async
service. Add a second docstring paragraph recording Pitfall 1: the Phase-1 STATE.md note about the
VAPID library being incompatible with the pinned `cryptography` concerns KEY GENERATION only;
`from_string` and `sign` work on the pinned version, so a hand-rolled ES256 signer must not appear
here.

POST to `subscription.endpoint` with the four headers plus the authorization, and a tighter per-call
timeout than the process default because push carries a 5-second SLA. Map statuses per the research
table: 201 success (provider id from `Location` when present); 400/403/413 definitive; 404/410 raise
a typed `PushSubscriptionRevoked` carrying the endpoint so the worker can set `revoked_at` and fall
back to email; 429 and 5xx retryable to 2 attempts. Cache the signed header per origin keyed by
`(origin, exp_bucket)` and re-sign within an hour of expiry — signing per message is an ECDSA
operation per send for a header valid across every subscription on that origin.

Guard the payload before encrypting: a `title` or `body` that is empty or whitespace raises, because
iOS silently revokes a subscription after roughly three pushes with nothing to show, and the service
worker that would surface the error is Phase 6.

Write `tests/unit/test_provider_push.py` using a real P-256 subscription keypair (the 04-02
`fake_push_subscription` helper) and `http_ece.decrypt` as the round-trip oracle, plus `respx` for
the request assertions — pass `host__in` as a TUPLE, never a list, or respx raises an unhashable-type
error at route-registration time with no reference to your test. Write
`tests/unit/test_push_revocation.py` for the 404/410 behaviour and the email-fallback signal, and
`tests/unit/test_retry_policy.py` as the cross-channel table test: per-channel attempt counts, the
retryable/definitive split, the `Retry-After` clamp in both delta-seconds and HTTP-date forms, and the
unparseable-value case.

Write `tests/unit/test_no_sync_sdk_imports.py` in the register of `tests/unit/test_no_setnx_expire_pairs.py`:
recursively collect every `.py` file under `services/` and `shared/`, strip full-line comments so an
explanatory comment can neither satisfy nor break the gate, and assert that none of them imports a
vendor notification SDK or a synchronous HTTP client. Name the forbidden distributions in a module
constant and state in the docstring that the reference implementations remain pinned and remain
legitimate CROSS-CHECK ORACLES from `tests/`, which is why the gate is scoped to the two source trees
rather than to the whole repository. Add the mandatory non-vacuity companion asserting the collected
file set is larger than a floor and contains named files from both trees, so a path typo cannot make
the gate vacuously green.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_provider_push.py tests/unit/test_push_revocation.py tests/unit/test_retry_policy.py tests/unit/test_no_sync_sdk_imports.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_provider_push.py tests/unit/test_push_revocation.py tests/unit/test_retry_policy.py tests/unit/test_no_sync_sdk_imports.py -q` exits 0.
    - `uv run python -c "import sys, services.notifier.providers.push; print(len([m for m in ('requests','aiohttp','urllib3') if m in sys.modules]))"` prints `0`.
    - `uv run python -c "import inspect, services.notifier.providers.push as p; s=inspect.getsource(p); print('http_ece' in s, 'urlsplit' in s, '12' in s)"` prints `True True True`.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A push payload encrypts, signs and sends with no vendor SDK in the process, decrypts back with the subscriber's key, derives its audience per endpoint, expires in 12 hours, and revokes rather than dead-letters on 404/410 — with a non-vacuous gate keeping the sync SDKs out of both source trees.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (04-05 slice)

**New modules:** `services/notifier/templates.py`, `services/notifier/pattern_hook.py`,
`services/notifier/providers/{__init__,base,email,sms,push}.py`, `tests/unit/gsm7.py`.

**New symbols — `templates.py`:** `TemplateContext`, `EmailBody`, `SMS_MAX_SEPTETS` (160),
`render_email()`, `render_sms()`, `render_push()`.

**New symbols — `pattern_hook.py`:** `estimate_window_text()` (returns `None` this phase; Phase 6
PATTERN-03 implements it).

**New symbols — `providers/base.py`:** `ProviderResult`, `ProviderError`,
`PushSubscriptionRevoked`, `MAX_RETRY_AFTER_SECONDS` (30), `parse_retry_after()`,
`send_with_retry()`.

**New symbols — provider clients:** `EmailProvider.send()`, `SmsProvider.send()`,
`PushProvider.send()`.

**New symbols — `services/notifier/config.py` (extended):** `resend_api_key()`, `resend_api_base()`,
`notify_from_email()`, `twilio_account_sid()`, `twilio_auth_token()`,
`twilio_messaging_service_sid()`, `twilio_api_base()`, `twilio_status_callback_url()`,
`vapid_private_key()`, `vapid_public_key()`, `vapid_subject()`, `email_enabled()`, `sms_enabled()`,
`push_enabled()`.

**New metrics — `shared/metrics.py` (appended at the single definition site):**
`notification_latency_seconds` (Histogram, label `channel`; exposed sample
`notification_latency_seconds_bucket`), `notifications_total` (Counter, labels `channel`, `status`;
exposed sample `notifications_total`, metric family `notifications`).

**Outbound HTTP endpoints:** `POST {RESEND_API_BASE}/emails`,
`POST {TWILIO_API_BASE}/2010-04-01/Accounts/{sid}/Messages.json`, `POST {subscription.endpoint}`.

**Email headers emitted:** `List-Unsubscribe`, `List-Unsubscribe-Post`, `Idempotency-Key`.

**Env vars introduced:** `RESEND_API_KEY`, `RESEND_API_BASE`, `NOTIFY_FROM_EMAIL`, `TWILIO_API_BASE`,
`TWILIO_STATUS_CALLBACK_URL`, `NOTIFY_DRY_RUN`. (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_MESSAGING_SERVICE_SID`, `VAPID_*` already exist.) All added to `.env.example` by 04-07.

**New gate:** `tests/unit/test_no_sync_sdk_imports.py` over `services/**` and `shared/**`, with a
non-vacuity companion.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| notifier -> Resend / Twilio / push service | Outbound HTTPS carrying a bearer token, HTTP Basic credentials and a VAPID JWT |
| provider response -> notifier | Attacker-influenceable headers, notably `Retry-After` |
| Postgres ciphertext -> `SmsProvider` | The single point where a phone number exists in plaintext |
| VAPID private key -> every subscriber | One key grants push capability over every subscription |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-04-29 | Denial of Service | provider-controlled `Retry-After` used to park the pipeline | high | mitigate | `parse_retry_after` handles both forms, clamps to `MAX_RETRY_AFTER_SECONDS = 30`, treats unparseable as absent; beyond the clamp the job dead-letters instead of waiting |
| T-04-30 | Information Disclosure | rendered body, recipient, `Authorization` header or API key in a log line | critical | mitigate | Logged by shape only; the 04-01 `_redact_secrets` extension covers `to`, `phone`, `body`, `html`, `endpoint`, `authorization`, `api_key` and every provider secret name |
| T-04-31 | Elevation of Privilege | VAPID private key exposure grants permanent push over every subscriber | high | mitigate | Read from env only, never committed, already in the redaction set; one keypair per environment; a unit test asserts the configured public key matches the signed header so a swapped key is caught in CI |
| T-04-32 | Spoofing | a mismatched or over-long-lived VAPID JWT accepted by the wrong service | medium | mitigate | Per-endpoint `aud` derived with `urlsplit`; `exp` explicitly 12 h; header cached per ORIGIN, never globally |
| T-04-33 | Tampering | a synchronous vendor SDK entering the async service | high | mitigate | `tests/unit/test_no_sync_sdk_imports.py` over `services/**` and `shared/**` with comment stripping and a non-vacuity floor; the reference SDKs stay usable from `tests/` as oracles |
| T-04-34 | Information Disclosure | phone plaintext living outside the send path | high | mitigate | `decrypt_phone` is called in `providers/sms.py` and nowhere else; `InvalidTag` caught by type and recorded as a code, never as a message |
| T-04-35 | Denial of Service | an oversized or empty push payload silently revoking an iOS subscription | medium | mitigate | Non-empty `title` and `body` enforced before encryption; payload size bounded well under the 4096-byte floor push services must accept |
| T-04-SC | Tampering | package-manager installs | high | mitigate | Zero packages added; every library used is already pinned and was version-verified in `.venv` (research §Package Legitimacy Audit). The reference SDKs stay pinned as test-only oracles |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/unit/test_no_sync_sdk_imports.py tests/unit/test_no_setnx_expire_pairs.py -q` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run python -c "import sys, services.notifier.providers.push, services.notifier.providers.email, services.notifier.providers.sms; print(len([m for m in ('requests','aiohttp','urllib3') if m in sys.modules]))"` prints `0`.
</verification>

<success_criteria>
- Three provider clients exist, all over the shared `httpx` singleton, none importing a vendor SDK.
- The push payload round-trips through a real subscriber keypair, with a per-endpoint audience and a 12-hour expiry.
- Every seeded restaurant name fits one GSM-7 SMS segment with a full 32-byte signed link.
- The retry policy's attempt counts, retryable split and clamped `Retry-After` each have an assertion.
- `shared/metrics.py` still has exactly one definition site and still imports twice without raising.
</success_criteria>

<output>
Create `.planning/phases/04-notification-pipeline/04-05-SUMMARY.md` when done
</output>
