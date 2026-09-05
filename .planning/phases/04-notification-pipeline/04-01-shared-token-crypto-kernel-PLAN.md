---
phase: 04-notification-pipeline
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - shared/tokens.py
  - shared/links.py
  - shared/crypto.py
  - shared/crash_hook.py
  - shared/twilio_signature.py
  - shared/svix_signature.py
  - shared/telemetry.py
  - services/state_machine/config.py
  - tests/unit/fixtures/__init__.py
  - tests/unit/fixtures/vectors.py
  - tests/unit/test_tokens.py
  - tests/unit/test_links.py
  - tests/unit/test_crypto.py
  - tests/unit/test_telemetry_redaction.py
  - tests/unit/test_twilio_signature.py
  - tests/unit/test_svix_signature.py
autonomous: true
requirements: [NOTIF-04, NOTIF-07]

estimate:
  tokens: 62000
  raw_tokens: 62000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`sign_token('go', {'n': <notification_log_id>})` produces `base64url(canonical_json).base64url(hmac_sha256)` with a FULL 32-byte signature and NO `iat`/`exp` claim, and `verify_token(token, expected_purpose='go')` returns the payload dict; the same token presented with `expected_purpose='unsubscribe'` raises `TokenPurposeMismatch` (D-82, D-81a/BC-2, research §Signed Tokens)."
    - "`go_link_sms(token)` renders `{host}/go/{token}` with NO URL scheme, and for a 10-digit `notification_log.id` the whole link is at most 94 characters — the measured budget BC-2 needs to fit the SMS body in one 160-septet GSM-7 segment (D-81a)."
    - "`platform_booking_url('opentable', ...)` emits `rid`, `datetime={date}T{HH:MM}` and `covers`; `platform_booking_url('resy', ...)` emits a percent-encoded slug plus `date` and `seats`; both templates carry a `TODO(spike)` marker naming them as unverified (D-83)."
    - "Signature verification uses `hmac.compare_digest` in `shared/tokens.py`, `shared/twilio_signature.py` and `shared/svix_signature.py` — a source scan in `tests/unit/test_tokens.py` proves no `==` comparison of a signature or digest exists in any of the three modules (research §Security Domain, ASVS V6)."
    - "A token signed under `HMAC_MGMT_SECRET_V1` still verifies while `HMAC_TOKEN_VERSION=2` and `now < HMAC_GRACE_UNTIL`, and raises `TokenVersionUnknown` once the grace date has passed — the Phase-5 WATCH-03 rotation contract, proven here (D-82)."
    - "`encrypt_phone` / `decrypt_phone` round-trip an E.164 number through AES-256-GCM with a fresh 12-byte nonce per call (two encryptions of the same number differ), a tampered blob raises `cryptography.exceptions.InvalidTag`, and a key that does not base64-decode to exactly 32 bytes raises a `ValueError` naming `PHONE_ENCRYPTION_KEY` at validation time rather than at first send (D-85)."
    - "`phone_hash` is stable across `+1 (555) 123-4567`, `+1-555-123-4567` and `+15551234567` because all three canonicalise to `+15551234567` before hashing — one canonicalisation function used on both write and lookup, so an inbound STOP can never silently match nothing (D-85, research §Phone Encryption)."
    - "`CRASH_HOOK_ENVS`, `crash_hook_allowed()` and `crash_after()` are DEFINED in `shared/crash_hook.py` and RE-EXPORTED from `services/state_machine/config.py` through `__all__`; the whole Phase-2 unit suite and `tests/integration/test_state_machine_chaos.py` stay green with zero behaviour change (D-88, research OQ-1)."
    - "`twilio_signature(auth_token, url, params)` reproduces all four published Twilio vectors byte-for-byte, and the JSON-body variant reproduces the `bodySHA256` vector; a tampered parameter set fails verification (D-84, research §Twilio inbound signature)."
    - "`verify_svix_signature` reproduces both published Svix vectors, rejects a tampered body, accepts a multi-signature header containing one valid entry, and rejects a timestamp more than 300 s from now (D-84, research §Resend webhooks)."
    - "`shared/telemetry.py::_redact_secrets` masks `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`, every `HMAC_MGMT_SECRET_V*`, and the value-shaped keys `phone`, `to`, `to_e164`, `body`, `sms_body`, `html`, `endpoint`, `p256dh`, `auth`, `token` — ON TOP OF the Phase-3 03-02 case-insensitive set, whose existing assertions all still pass (D-72 code_context, research §Pitfall 12)."
    - "PROBE NOTIF-07/unclassified — flagged assumption: the two platform booking URL schemes are `[ASSUMED]` (research A1/A2). The unit tests assert URL SHAPE only (parameter names, date/time formatting, slug encoding) and never live behaviour; a second OpenTable candidate form is recorded in a module comment so the spike has both to try."
    - statement: "`https://www.opentable.com/restref/client/?rid=…&datetime=…&covers=…` and `https://resy.com/cities/ny/{slug}?date=…&seats=…` land the user on the correct pre-filled booking slot. OpenTable's public RestRef API is reported shut down and both forms come from third-party reconstructions; only a human clicking a produced link can confirm them (research A1/A2, SC5)."
      verification: backstop
  artifacts:
    - shared/tokens.py
    - shared/links.py
    - shared/crypto.py
    - shared/crash_hook.py
    - shared/twilio_signature.py
    - shared/svix_signature.py
    - tests/unit/fixtures/vectors.py
    - tests/unit/test_tokens.py
    - tests/unit/test_links.py
    - tests/unit/test_crypto.py
    - tests/unit/test_twilio_signature.py
    - tests/unit/test_svix_signature.py
  key_links:
    - "`sign_token('go', {'n': id})` -> `go_link_sms()` -> `render_sms()` (04-05) -> the 160-septet budget. Adding ANY claim to the `go` payload pushes the SMS into a second segment or into UCS-2; the token shape and the SMS budget are one coupled contract (BC-2)."
    - "`verify_token(..., expected_purpose=...)` -> `GET /go/{token}` and `POST /unsubscribe/{token}` (04-04). The `p` claim is the only thing preventing an unsubscribe token from being replayed as a click token and vice versa."
    - "`phone_hash()` -> `users.phone_hash` (04-02 migration) -> the inbound STOP lookup (04-04). One canonicalisation function on both sides; a mismatch is a silent TCPA failure, not a visible error."
    - "`shared/crash_hook.py` -> `services/state_machine/config.py` re-export AND `services/notifier/workers.py` (04-06). One definition site for a safety interlock that arms a SIGKILL; two readers of it is one too many (Phase-2 CR note, D-88)."
  prohibitions:
    - "MUST NOT compare a signature, MAC or digest with `==` or `!=` anywhere in `shared/tokens.py`, `shared/twilio_signature.py` or `shared/svix_signature.py` — every comparison goes through `hmac.compare_digest`."
    - "MUST NOT truncate the HMAC to buy characters. The 32-byte signature stays; BC-2's savings come from dropping the URL scheme and the `iat`/`exp` claims, never from weakening the MAC."
    - "MUST NOT parse, trust or act on a token payload before its MAC verifies — the payload is attacker-supplied JSON until then, and the MAC is computed over the base64url string, never over re-serialised JSON."
    - "MUST NOT write a phone number, a signed token, an HMAC secret, `PHONE_ENCRYPTION_KEY` or a provider credential into a log line, an exception message, Postgres, Kafka or a file on disk."
    - "MUST NOT reuse an AES-GCM nonce; every `encrypt_phone` call draws a fresh 12 bytes from `os.urandom`."
    - "MUST NOT copy `CRASH_HOOK_ENVS` or `crash_hook_allowed()` into a second module. The notifier imports the shared definition; it never re-declares the allowlist."
---

<objective>
Build the pure `shared/` kernel every later Phase-4 plan links against: versioned HMAC capability
tokens, platform deep links, AES-256-GCM phone encryption with a deterministic lookup hash, the two
inbound-webhook signature verifiers, and the crash-hook move that gives two services one safety
interlock instead of two copies.

Purpose: every one of these is a place where a wrong implementation produces a SILENT no-op — a
dropped push, a STOP that matches nothing, a forged unsubscribe that pauses a stranger's watches —
rather than an exception. All of them are pure functions over `(secret, bytes)`, so all of them are
falsifiable in CI against published vectors before a single byte crosses the network.
Output: six new `shared/` modules, one re-export edit, an extended redactor, a vectors fixture, and
five unit test files that pin every boundary.
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
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — one signed `go` deep link, minted, rendered SMS-short, and verified back</name>
  <files>shared/tokens.py, shared/links.py, tests/unit/test_tokens.py, tests/unit/test_links.py</files>
  <read_first>
    - shared/redis_keys.py lines 1-10 and lines 60-100 (the `Named symbols:` docstring convention, the `quote(part, safe="")` injectivity discipline and the reasoning density every shared module carries)
    - shared/events.py lines 20-70 (`NAMESPACE_MISE`'s "NEVER CHANGE THIS VALUE" comment — the tone for a permanent contract)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Signed Tokens (measured)" (the measured token sizes table, the five verification rules, and the two `mypy --strict` narrowing idioms)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Blocking Corrections" BC-2 (why the `go` payload carries no `iat`/`exp` and why the scheme is dropped)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Deep Links" (the two [ASSUMED] URL forms, the second OpenTable candidate, the `booking_token` fallback note)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-82, §D-83, §D-81a
    - .env.example lines 60-64 (the existing `HMAC_MGMT_SECRET_V1` placeholder style)
  </read_first>
  <behavior>
    - `sign_token("go", {"n": 123456})` then `verify_token(tok, expected_purpose="go")` returns `{"v": 1, "p": "go", "n": 123456}`.
    - The produced token contains exactly one `.`; the payload half base64url-decodes to canonical JSON with sorted keys and no spaces; the signature half decodes to exactly 32 bytes.
    - Flipping any single character of either half raises `TokenSignatureInvalid`; a token with no `.` raises `TokenMalformed`.
    - A `go` token presented with `expected_purpose="unsubscribe"` raises `TokenPurposeMismatch` and never returns a payload.
    - An `unsubscribe` token past its `exp` raises `TokenExpired`; the same token before `exp` verifies.
    - With `HMAC_TOKEN_VERSION=2` and `HMAC_MGMT_SECRET_V2` set, a token minted under v1 verifies while `HMAC_GRACE_UNTIL` is in the future and raises `TokenVersionUnknown` once it is in the past.
    - A payload naming an unknown `p` value raises `TokenPurposeMismatch` even when its MAC is valid.
    - `go_link_sms(sign_token("go", {"n": 1234567890}))` is at most 94 characters and contains no `://`.
    - `platform_booking_url("opentable", "42", "carbone", "2026-05-01", 2, "19:30")` contains `rid=42`, `datetime=2026-05-01T19:30` and `covers=2`.
    - `platform_booking_url("resy", "834", "mission-chinese-food", "2026-05-01", 4, "20:00")` contains the URL-encoded slug, `date=2026-05-01` and `seats=4`.
    - An unknown source raises `ValueError` naming the source rather than returning a plausible-looking wrong URL.
  </behavior>
  <action>
Write `shared/tokens.py` as the project's capability-token contract (D-82). Module docstring in the
`shared/redis_keys.py` register: a `Named symbols:` line, and prose stating that this is the Phase-5
WATCH-03 rotation contract defined early because Phase-4 deep links and unsubscribe links need it now.

Public surface: `TOKEN_PURPOSES` (a `frozenset` of `go`, `unsubscribe`, `sms_stop`);
`UNSUBSCRIBE_TOKEN_TTL_SECONDS`; the exception hierarchy `TokenError` with subclasses
`TokenMalformed`, `TokenSignatureInvalid`, `TokenPurposeMismatch`, `TokenExpired`,
`TokenVersionUnknown`; lazy env accessors `token_version()` reading `HMAC_TOKEN_VERSION` (default 1),
`grace_until()` reading `HMAC_GRACE_UNTIL` as an ISO date, and a private secret lookup reading
`HMAC_MGMT_SECRET_V{n}` and raising `TokenVersionUnknown` when that variable is unset; and the pair
`sign_token(purpose, claims, *, ttl_seconds=None) -> str` / `verify_token(token, *, expected_purpose,
now=None) -> dict[str, object]`. Every env read is a FUNCTION, never a module constant — the
`services/poller/config.py` import-time freeze is the documented defect this avoids.

Encoding: the payload is `{"v": version, "p": purpose, **claims}` plus `iat`/`exp` ONLY when
`ttl_seconds` is given, serialised with `json.dumps(payload, separators=(",", ":"), sort_keys=True)`,
then base64url with the padding stripped. The MAC is HMAC-SHA256 over the ENCODED PAYLOAD STRING's
bytes — never over re-serialised JSON, or a canonicalisation difference silently breaks verification —
and is emitted at its full 32 bytes, base64url, padding stripped. `sign_token` refuses a purpose
outside `TOKEN_PURPOSES` and refuses `ttl_seconds` for the `go` purpose, because the `go` link's
lifetime is bounded by the `notification_log` row it names, and each of `iat`/`exp` costs septets the
SMS body does not have (BC-2 measured 153 of 160 used at the recommended shape).

`verify_token` order of operations, each step stated in a comment with its reason: reject a token
with no separator before any decode; base64url-decode the payload half with padding restored; read
`v` and look up that version's secret, accepting `version - 1` only while `grace_until()` is in the
future; recompute the MAC over the encoded payload string and compare with `hmac.compare_digest`;
only THEN parse the JSON; reject a `p` that is not `expected_purpose`; reject an `exp` in the past.
Under `mypy --strict`, `json.loads` returns `Any`, so bind it to a local annotated `object` and narrow
with `isinstance(..., dict)` before use, and validate that `v` is an `int` and `p` a `str` before
indexing — an attacker controls the whole payload until the MAC verifies.

Write `shared/links.py` (D-83). Lazy `public_base_url()` reading `PUBLIC_BASE_URL` (default
`https://mise.place`) and `public_host()` returning its netloc, so the SMS link can drop the scheme
(BC-2). `go_url(token)` and `unsubscribe_url(token)` return absolute HTTPS URLs — RFC 8058 requires
the `List-Unsubscribe` URI to be HTTPS. `go_link_sms(token)` returns the scheme-less
`{host}/go/{token}` form and nothing else. `platform_booking_url(source, platform_id, slug, date,
party_size, time_slot, booking_token=None)` dispatches on source through module-level template
constants `OPENTABLE_BOOKING_URL_TEMPLATE` and `RESY_BOOKING_URL_TEMPLATE`, each carrying an
`[ASSUMED]` marker and a `TODO(spike)` line in a comment above it; record the alternate OpenTable
candidate form (`/booking/experiences-availability`) in that comment so the spike has both to try, and
document `booking_token` as the preferred-slot input whose shape is not yet confirmed, currently
unused in the returned URL. Percent-encode the slug with `quote(slug, safe="")` and refuse an unknown
source with a `ValueError` naming it.

Write `tests/unit/test_tokens.py` and `tests/unit/test_links.py` covering every bullet in
`<behavior>`. The tracer assertion that ties the two modules together lives in `test_links.py`: mint a
real `go` token for a 10-digit id with a 32-byte-secret environment, render it through
`go_link_sms`, and assert the whole link is within the 94-character budget the SMS template depends
on, computing the host from `PUBLIC_BASE_URL` rather than from a literal — a longer host is the most
likely way this regresses. Add to `test_tokens.py` a source-scan test that reads `shared/tokens.py`,
strips full-line comments, and asserts the module names `compare_digest` and that no line comparing a
variable whose name contains `sig`, `mac` or `digest` uses an equality operator.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_tokens.py tests/unit/test_links.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_tokens.py tests/unit/test_links.py -q` exits 0.
    - `uv run pytest tests/unit -q` exits 0 — the whole pre-existing unit suite stays green.
    - `HMAC_MGMT_SECRET_V1=0123456789abcdef0123456789abcdef PUBLIC_BASE_URL=https://mise.place uv run python -c "from shared.tokens import sign_token; from shared.links import go_link_sms; t=sign_token('go',{'n':1234567890}); l=go_link_sms(t); print(len(l), l.count('.'), '://' in l)"` prints a first field `&lt;= 94`, a second field of `1`, and a third field of `False`.
    - `uv run python -c "import base64,json,os; os.environ['HMAC_MGMT_SECRET_V1']='k'*32; from shared.tokens import sign_token; p,s=sign_token('go',{'n':123456}).split('.'); print(len(base64.urlsafe_b64decode(s+'==')))"` prints `32`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One `go` token is minted, rendered into an SMS-length-safe scheme-less link, and verified back with its purpose and version enforced — the full NOTIF-07 deep-link path, end to end, in pure functions.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Phone encryption and lookup hash, the shared crash hook, and the extended log redactor</name>
  <files>shared/crypto.py, shared/crash_hook.py, services/state_machine/config.py, shared/telemetry.py, tests/unit/test_crypto.py, tests/unit/test_telemetry_redaction.py</files>
  <precondition>Phase 3 plan 03-02 has landed, so `shared/telemetry.py::_redact_secrets` is already the case-insensitive form covering `cookie`, `authorization`, `api_key` and the Resy keys. This task EXTENDS that function and its test file; if the function is still the four-key Phase-2 version, stop and report the ordering violation rather than rewriting it.</precondition>
  <read_first>
    - shared/telemetry.py lines 86-105 (`_redact_secrets`, the `_REDACTED` sentinel and the `RESY_ACCOUNT_*_PASSWORD` prefix rule) and lines 20-84 (`safe_error` and the split it documents against `_failure_shape`)
    - tests/unit/test_telemetry_redaction.py in full (the assertions to EXTEND, never replace)
    - services/state_machine/config.py lines 1-40 (the `__all__` re-export idiom used for `CONFIRM_DELAY_MS`) and lines 66-90 (`CRASH_HOOK_ENVS`, `crash_hook_allowed`, `crash_after` — the exact text to move)
    - services/state_machine/main.py lines 95-110 (the startup interlock that consumes `crash_hook_allowed`) and services/state_machine/consumer.py lines 126-145 (`_maybe_crash` and its docstring on why there must be ONE reader)
    - tests/unit/test_state_machine_startup.py (the tests that must keep passing unchanged)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Phone Encryption and Hashing" (the measured 40-byte ciphertext layout, the key-length guard rationale, the canonicalisation rule)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Pitfall 12" (the exact key list to add and the Phase-3 collision note)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-85, §D-88, §D-89
  </read_first>
  <behavior>
    - `decrypt_phone(encrypt_phone("+15551234567"))` returns `"+15551234567"`.
    - Two `encrypt_phone` calls on the same input produce different blobs; the first 12 bytes differ.
    - Flipping one byte of a blob and decrypting raises `cryptography.exceptions.InvalidTag`.
    - A `PHONE_ENCRYPTION_KEY` that base64-decodes to 16 bytes raises `ValueError` whose message names the variable and the required length; the same happens for a value that is not valid base64.
    - `canonical_e164` maps `"+1 (555) 123-4567"`, `"+1-555-123-4567"` and `"+15551234567"` to one identical string; `phone_hash` of all three is one identical 64-character lowercase hex digest.
    - `crash_hook_allowed()` is `True` only for `ENV` in `{dev, test, ci, local}` (case- and whitespace-insensitive) and `False` for unset, empty, `staging`, `prod`, `production` and `PROD`.
    - `maybe_crash("nx_claim")` is a no-op when `MISE_CRASH_AFTER` is unset or names a different stage.
    - `from services.state_machine.config import CRASH_HOOK_ENVS, crash_hook_allowed, crash_after` still resolves and returns the same values as the shared module.
    - Every key in the extended set is masked case-insensitively; `restaurant_id`, `latency_ms`, `channel` and `watch_id` pass through untouched.
  </behavior>
  <action>
Write `shared/crypto.py` (D-85, D-89). `NONCE_BYTES = 12` as a `Final[int]` with a comment stating
that 12 is the AES-GCM standard nonce length and 16 is the common wrong answer. Lazy accessors read
`PHONE_ENCRYPTION_KEY` (base64, must decode to exactly 32 bytes) and `PHONE_HASH_SECRET`; the length
check is EXPLICIT and raises a `ValueError` naming the variable, because without it a short key fails
inside `cryptography` with an unhelpful message at the moment of a send rather than at startup. Expose
`assert_crypto_env() -> None` so a service lifespan can validate both variables at boot.

`encrypt_phone(e164) -> bytes` returns `nonce || AESGCM(key).encrypt(nonce, e164.encode(), None)` —
the layout is nonce-then-ciphertext-then-tag, stored whole in the existing `users.phone` BYTEA
column, and the docstring must say so because Phase 5 is the writer and this phase only decrypts.
`decrypt_phone(blob) -> str` splits at `NONCE_BYTES`. Per D-89 there is NO associated data in v1:
record that as a DECISION in the docstring, not an omission — the threat it defends (write access to
`users.phone` without the key) is out of the v1 model, and adding AAD later is a data migration, so
it is a v2 hardening item.

`canonical_e164(raw) -> str` keeps a leading `+` and the digits and drops everything else; it is the
ONE canonicalisation, used on both write and lookup. `phone_hash(raw) -> str` returns the lowercase
hex HMAC-SHA256 of `canonical_e164(raw)` under `PHONE_HASH_SECRET`. State in the docstring that a
divergence between the write-side and lookup-side spelling makes an inbound STOP silently match
nothing, which is a TCPA exposure rather than a cosmetic bug.

Create `shared/crash_hook.py` by MOVING — not copying — `CRASH_HOOK_ENVS`, `crash_hook_allowed()`
and `crash_after()` out of `services/state_machine/config.py` verbatim, docstrings and fail-closed
reasoning intact, and add `maybe_crash(stage: str) -> None` (a no-op unless `crash_after()` names the
stage, otherwise `os.kill(os.getpid(), signal.SIGKILL)`) with the Phase-4 stage list in its docstring:
`nx_claim`, `provider_ack`, `log_insert`, `sent_publish`, `commit`. Then edit
`services/state_machine/config.py` to import the three moved names from `shared.crash_hook` and keep
them in `__all__` with the `# noqa: F401` re-export comment the module already uses for
`CONFIRM_DELAY_MS`. Do NOT touch `services/state_machine/consumer.py::_maybe_crash` — it already
reads through `config.crash_after`, so the move is behaviour-preserving and the Phase-2 chaos test
must keep passing untouched.

Extend `shared/telemetry.py::_redact_secrets` on top of the Phase-3 form: add the exact names
`RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`, a prefix rule
for `HMAC_MGMT_SECRET_V`, and the value-shaped keys `phone`, `to`, `to_e164`, `body`, `sms_body`,
`html`, `endpoint`, `p256dh`, `auth`, `token`, all matched case-insensitively. Note in the docstring
that the value-shaped half is deliberately broad — a rendered SMS body carries a signed capability
URL and a phone number, so over-redacting a field called `body` is strictly cheaper than the one time
it is a real message — and that a key-name redactor still cannot save a caller who logs a whole header
mapping under a benign key, which is why the providers are separately forbidden from doing that.

Write `tests/unit/test_crypto.py` covering every crypto bullet in `<behavior>`, and APPEND to
`tests/unit/test_telemetry_redaction.py` a parametrised case per new key plus a pass-through case for
the benign field names — extending the file, never rewriting the existing Phase-2/Phase-3 assertions.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_crypto.py tests/unit/test_telemetry_redaction.py tests/unit/test_state_machine_startup.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_crypto.py tests/unit/test_telemetry_redaction.py -q` exits 0.
    - `uv run pytest tests/unit -q` exits 0 — every pre-existing Phase-2 test, including `test_state_machine_startup.py`, stays green.
    - `uv run python -c "import shared.crash_hook as c, services.state_machine.config as sc; print(c.CRASH_HOOK_ENVS == sc.CRASH_HOOK_ENVS, sc.crash_hook_allowed is c.crash_hook_allowed, sc.crash_after is c.crash_after)"` prints `True True True`.
    - `grep -c "def " shared/crypto.py` returns at least `6`.
    - `PHONE_HASH_SECRET=s uv run python -c "from shared.crypto import phone_hash as h; a=h('+1 (555) 123-4567'); b=h('+15551234567'); print(a==b, len(a))"` prints `True 64`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Phone numbers encrypt and decrypt under a validated 32-byte key with a deterministic lookup hash, the SIGKILL interlock has exactly one definition site with Phase 2 unchanged, and every new secret and every payload-shaped log field is masked.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Twilio and Svix inbound signature verifiers, against published vectors</name>
  <files>shared/twilio_signature.py, shared/svix_signature.py, tests/unit/fixtures/__init__.py, tests/unit/fixtures/vectors.py, tests/unit/test_twilio_signature.py, tests/unit/test_svix_signature.py</files>
  <read_first>
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Twilio inbound signature" (the twelve-line algorithm, the four verified vectors with their exact URLs and tokens, the `bodySHA256` JSON variant and its vector, and the proxy/`request.url` warning)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Resend webhooks — Svix" (the signed-content format, the `whsec_` prefix strip, both published vectors with their ids/timestamps/bodies, the multi-signature header case and the tolerance rule)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Pitfall 9" (why the verification URL comes from config, never from `request.url`)
    - shared/redis_keys.py lines 1-12 (the pure-module docstring convention these two files copy)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-84
  </read_first>
  <behavior>
    - `twilio_signature("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", VECTOR_PARAMS)` equals `RSOYDt4T1cUTdK1PDd93/VVr8B8=`, and the other three published `(url, token)` pairs each reproduce their documented value.
    - Changing one character of one parameter value changes the signature; `verify_twilio_signature` returns `False` for the tampered set and `True` for the original.
    - `body_sha256_hex(b'{"foo":1}')`-style JSON-variant verification reproduces the documented `m5ij+9mPJiX/KSczbtotqDaCTzM=` for the recorded `bodySHA256` URL with an empty parameter set.
    - An empty parameter mapping is legal and produces the signature of the URL alone — it is exactly the JSON-variant case, not an error.
    - `verify_svix_signature` returns `True` for both published vectors and `False` when one byte of the body changes.
    - A `svix-signature` header holding several space-delimited `v1,<b64>` entries verifies when ANY entry matches; a header with none matching returns `False`.
    - A `svix-timestamp` more than `SVIX_TOLERANCE_SECONDS` from `now` returns `False` even when the MAC is correct; a non-numeric timestamp returns `False` rather than raising.
  </behavior>
  <action>
Write `shared/twilio_signature.py` (D-84). `twilio_signature(auth_token, url, params) -> str` is the
sanctioned hand-roll: base64 of HMAC-SHA1 over `url` followed by `k + params[k]` for `k` in
`sorted(params)`. The docstring must say WHY hand-rolling is right here and only here — the SDK is a
synchronous `requests` client that may not enter `services/` or `shared/`, the algorithm is twelve
lines, and it is falsifiable against four published vectors, which is the whole difference between a
hand-roll and a guess. Add `verify_twilio_signature(auth_token, url, params, header) -> bool` using
`hmac.compare_digest`, and `body_sha256_hex(body: bytes) -> str` for the JSON-body variant, where
Twilio appends `bodySHA256=<hex>` to the URL and signs that URL with an EMPTY parameter set. State in
the module docstring that the URL passed in must be the URL Twilio was CONFIGURED with — built from
`TWILIO_WEBHOOK_BASE_URL` plus the route path — and never `request.url`, which behind a proxy reports
the internal scheme and host and makes every inbound STOP fail verification with no clue.

Write `shared/svix_signature.py` (D-84). `SVIX_TOLERANCE_SECONDS = 300` as a `Final[int]`.
`verify_svix_signature(secret, svix_id, svix_timestamp, body, signature_header, *, now=None) -> bool`
strips a `whsec_` prefix, base64-decodes the remainder as the key, HMAC-SHA256s the signed content
`f"{svix_id}.{svix_timestamp}.{body.decode()}"`, and compares constant-time against every
space-delimited `v1,`-prefixed entry in the header. Reject outside the tolerance window BEFORE
comparing, and treat a non-numeric timestamp as a rejection rather than an exception. The docstring
must state that the body must be the RAW request bytes — never a Pydantic-parsed model re-serialised
— because the signature is sensitive to the slightest change.

Create `tests/unit/fixtures/__init__.py` and `tests/unit/fixtures/vectors.py` holding the four Twilio
vectors (URL, auth token, parameter mapping, expected signature), the `bodySHA256` JSON vector, and
the two Svix vectors (secret, id, timestamp, body, expected header) as module constants shaped for
`pytest.mark.parametrize`, each annotated with its source. Write `tests/unit/test_twilio_signature.py`
and `tests/unit/test_svix_signature.py` driving every bullet in `<behavior>` from those constants,
including a test that asserts the fixture module actually exposes four Twilio cases and two Svix cases
so a truncated fixture cannot make the parametrised suite vacuously green.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_twilio_signature.py tests/unit/test_svix_signature.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_twilio_signature.py tests/unit/test_svix_signature.py -q` exits 0.
    - `uv run python -c "from tests.unit.fixtures import vectors as v; print(len(v.TWILIO_VECTORS), len(v.SVIX_VECTORS))"` prints `4 2`.
    - `uv run python -c "from shared.twilio_signature import twilio_signature as t; print(t('12345','https://mycompany.com/myapp.php?foo=1&bar=2',{'CallSid':'CA1234567890ABCDE','Caller':'+14158675309','Digits':'1234','From':'+14158675309','To':'+18005551212'}))"` prints `RSOYDt4T1cUTdK1PDd93/VVr8B8=`.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Both inbound-webhook signature schemes are implemented as pure functions with no vendor SDK, and each reproduces every published vector while rejecting tampering, replay and an out-of-window timestamp.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (04-01 slice)

**New modules:** `shared/tokens.py`, `shared/links.py`, `shared/crypto.py`, `shared/crash_hook.py`,
`shared/twilio_signature.py`, `shared/svix_signature.py`, `tests/unit/fixtures/vectors.py`.

**New symbols — `shared/tokens.py`:** `TOKEN_PURPOSES`, `UNSUBSCRIBE_TOKEN_TTL_SECONDS`, `TokenError`,
`TokenMalformed`, `TokenSignatureInvalid`, `TokenPurposeMismatch`, `TokenExpired`,
`TokenVersionUnknown`, `token_version()`, `grace_until()`, `sign_token()`, `verify_token()`.

**New symbols — `shared/links.py`:** `OPENTABLE_BOOKING_URL_TEMPLATE`, `RESY_BOOKING_URL_TEMPLATE`,
`public_base_url()`, `public_host()`, `go_url()`, `go_link_sms()`, `unsubscribe_url()`,
`platform_booking_url()`.

**New symbols — `shared/crypto.py`:** `NONCE_BYTES`, `encrypt_phone()`, `decrypt_phone()`,
`canonical_e164()`, `phone_hash()`, `assert_crypto_env()`.

**New symbols — `shared/crash_hook.py`:** `CRASH_HOOK_ENVS`, `crash_hook_allowed()`, `crash_after()`,
`maybe_crash()` (crash stages: `nx_claim`, `provider_ack`, `log_insert`, `sent_publish`, `commit`).

**New symbols — signature modules:** `twilio_signature()`, `verify_twilio_signature()`,
`body_sha256_hex()`; `SVIX_TOLERANCE_SECONDS`, `verify_svix_signature()`.

**Routes referenced (implemented in 04-04):** `/go/{token}`, `/unsubscribe/{token}`.

**Env vars introduced:** `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`, `HMAC_MGMT_SECRET_V{n}` (V1
already in `.env.example`), `PUBLIC_BASE_URL`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`,
`TWILIO_WEBHOOK_BASE_URL` (consumed in 04-04). All are added to `.env.example` by 04-07.

**Modified:** `services/state_machine/config.py` (re-export only, zero behaviour change),
`shared/telemetry.py` (`_redact_secrets` extended).
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| mail client / SMS client -> `/go`, `/unsubscribe` | An attacker-supplied token string crosses into the process; it is untrusted JSON until its MAC verifies |
| Twilio / Resend -> our webhook routes | Attacker-forgeable HTTP bodies and headers; only the signature distinguishes them from the real provider |
| Postgres `users.phone` -> `SmsProvider` | Ciphertext at rest crosses back into plaintext exactly once, at send time |
| process -> log stream | Every secret and every payload this plan introduces can reach a log field |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-04-01 | Spoofing | `shared/tokens.py::verify_token` | high | mitigate | Full 32-byte HMAC, no truncation; `hmac.compare_digest`; MAC verified over the encoded payload string BEFORE any JSON parse; unit tests for a flipped character in each half |
| T-04-02 | Elevation of Privilege | `shared/tokens.py` purpose claim | high | mitigate | `p` claim checked against the route's `expected_purpose`; an `unsubscribe` token replayed at `/go` raises `TokenPurposeMismatch`; unit-tested in both directions |
| T-04-03 | Information Disclosure | signature comparison in all three verifier modules | medium | mitigate | `hmac.compare_digest` everywhere; a source-scan test forbids `==` on any signature/MAC/digest variable |
| T-04-04 | Spoofing | `shared/twilio_signature.py` verification URL | high | mitigate | URL built from `TWILIO_WEBHOOK_BASE_URL` + route path, never `request.url` (Pitfall 9); consumed that way in 04-04 and unit-tested for both match and mismatch |
| T-04-05 | Tampering | `shared/svix_signature.py` replay | medium | mitigate | 300 s timestamp tolerance enforced before MAC comparison; non-numeric timestamp is a rejection |
| T-04-06 | Information Disclosure | `shared/crypto.py` phone plaintext, `shared/telemetry.py` log fields | high | mitigate | AES-256-GCM with a fresh 12-byte nonce; `InvalidTag` caught by type in the caller; `_redact_secrets` extended with every new secret name and the value-shaped keys `phone`/`to`/`body`/`token` |
| T-04-07 | Tampering | `shared/crypto.py` ciphertext-swap between user rows | low | accept | No AAD in v1 per D-89 — the attacker model requires write access to `users.phone` without the key, which is out of the v1 model; recorded in the module docstring as a v2 hardening item, not an oversight |
| T-04-08 | Denial of Service | `shared/crash_hook.py` SIGKILL interlock | critical | mitigate | Allowlist, not denylist: armed only when `ENV` is EXPLICITLY one of dev/test/ci/local; unset, blank, `staging` and `production` all refuse; one definition site, re-exported |
| T-04-SC | Tampering | package-manager installs | high | mitigate | This phase adds ZERO packages (research §Package Legitimacy Audit: no new-package attack surface). `python-multipart` is the one package that must NOT be added; the gate `tests/unit/test_no_new_runtime_deps.py` lands in 04-04 |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0 (whole unit tier, including every pre-existing Phase-1/2 test).
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run pytest tests/integration/test_state_machine_chaos.py -q -p no:cacheprovider` exits 0 or skips on a Docker-less host — the crash-hook move is behaviour-preserving.
- `uv run python -c "from tests.unit.fixtures import vectors as v; print(len(v.TWILIO_VECTORS), len(v.SVIX_VECTORS))"` prints `4 2`.
</verification>

<success_criteria>
- Six new pure `shared/` modules exist, each with a `Named symbols:` docstring line, each free of I/O.
- Every published Twilio and Svix vector is reproduced by our code in CI.
- The `go` token + link pair fits the SMS budget measured in BC-2, with a full 32-byte signature.
- Phase 2 keeps one — and only one — definition of the SIGKILL allowlist, and its tests are untouched.
- `mypy --strict` and `ruff` are clean across `shared/ services/ scripts/`.
</success_criteria>

<output>
Create `.planning/phases/04-notification-pipeline/04-01-SUMMARY.md` when done
</output>
