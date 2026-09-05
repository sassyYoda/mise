# Runbook — Resy credential capture and venue-id resolution

> **STATUS: pending-human**
>
> Every step in this runbook needs a real browser, a real Resy session and a human
> looking at DevTools. None of it is performable from a coding-agent context, and none of
> it is a blocking step for any plan in Phase 3: the code paths are built, tested and
> shipped against fixtures and a local stub, and stay switched off (`RESY_ENABLED=false`)
> until a human completes the steps below.
>
> **Nothing here has been performed yet.** `RESY_API_KEY` is unset, `RESY_ACCOUNTS_JSON`
> holds the placeholder from `.env.example`, and all 55 `resy_venue_id` values in
> `scripts/seed/restaurants.yml` are `null`.

Covers: D-24, D-61, D-63a, FOUND-06, research assumptions A2/A4/A5.
Related: `docs/admin-evidence/resy.md` (the account-creation evidence template).

---

## What is missing, and what each thing unblocks

| Secret / datum | Env var / file | Unblocks | Status |
|----------------|----------------|----------|--------|
| Resy API key | `RESY_API_KEY` | The `Authorization: ResyAPI api_key="…"` header on every `/4/find` call, and `scripts/resolve_resy_venue_ids.py` | pending-human |
| Per-account auth token | `RESY_ACCOUNTS_JSON` (cookie `auth_token`) | Authenticated availability (anonymous mode works but sees less) | pending-human |
| Numeric venue ids | `resy_venue_id` in `scripts/seed/restaurants.yml` | Any Resy job existing at all (D-63a) | pending-human — 31 unresolved |
| 3+ pre-auth accounts | `RESY_ACCOUNTS_JSON` | Context rotation across accounts (D-61) | pending-human — see `docs/admin-evidence/resy.md` |

---

## Step 1 — Capture `RESY_API_KEY` (5 minutes)

The Resy web app ships a public API key in every request it makes. It is not a user
secret, but it is treated as one everywhere in this repo: `shared/telemetry.py` redacts
`RESY_API_KEY` (and `api_key`, `authorization`, `cookie`, `x-resy-auth-token`) from every
structured log event, and no script in `scripts/` prints it.

1. Open <https://resy.com/cities/ny> in Chrome, logged in or not.
2. Open DevTools (Cmd+Option+I) → **Network** → filter `api.resy.com`.
3. Click any restaurant to trigger an availability request.
4. Select the request → **Headers** → **Request Headers** → copy the `Authorization`
   value. It looks like `ResyAPI api_key="AbCdEf123…"`.
5. Put **only the key**, not the `ResyAPI api_key="…"` wrapper, into `.env`:

   ```
   RESY_API_KEY=AbCdEf123…
   ```

   `.env` is gitignored. Mirror it to GCP Secret Manager the same way as
   `RESY_ACCOUNTS_JSON` (see `docs/admin-evidence/gcp.md`).

While you are in this Network panel, also record for the Phase-3 spike:

- the exact request path and query string of the availability call (research assumes
  `GET /4/find?lat=0&long=0&day=YYYY-MM-DD&party_size=N&venue_id=N`),
- the exact response body shape (research `[ASSUMED]` shape lives in exactly one file,
  `services/poller/sources/resy/fixtures.py`, each body carrying a `TODO(spike):` marker),
- whether the per-account token header is `X-Resy-Auth-Token` or the sibling
  `X-Resy-Universal-Auth` (assumption A5 — the header NAME is configurable via
  `RESY_AUTH_TOKEN_HEADER` precisely because this is unconfirmed).

---

## Step 2 — Capture account cookies

Follow `docs/admin-evidence/resy.md` → "Capture procedure (detailed)". The output is a
single-line JSON array in `.env` as `RESY_ACCOUNTS_JSON`.

**Cookies live in Playwright browser-context memory only.** Never in a database table,
never in a log line, never in a fixture (D-61, Pitfall 8).

---

## Step 3 — Resolve the numeric `resy_venue_id` values

**Why this step exists.** Every `resy_venue_id` in `scripts/seed/restaurants.yml` used to
be a URL slug (`"carbone-new-york-new-york"`). Resy's `/4/find` takes a **numeric**
venue id, the poller's job descriptor is `resy:{resy_venue_id}`, and `poll_loop` parses it
back with `int()`. A slug there raises `ValueError`, the poller logs
`invalid_restaurant_id` and `continue`s **without releasing the job**, so the job sits in
`sched:polls:inflight` and is re-enqueued by the reaper forever (research B-4).

Plan 03-03 split that field in two: `resy_url_slug` (the human slug, 31 populated) and
`resy_venue_id` (integer or `null`, `null` on all 55). **No placeholder integer was
minted.** A fake id in the 800_000_000+ range would still be a syntactically valid job,
so the fleet would poll it — against whatever real venue holds that id, with no signal
that the data was invented (T-03-10). Null is the honest value, and the seed skips it.

### Dry run first (no credentials, no network, writes nothing)

```bash
uv run python scripts/resolve_resy_venue_ids.py --dry-run
```

Exit codes follow the `scripts/check_poll_success.py` convention:

| Code | Meaning |
|------|---------|
| 0 | Everything requested was resolved |
| 1 | One or more lookups failed |
| 2 | Preconditions not met (no `RESY_API_KEY`, or `--dry-run`) |

A dry run always exits 2 and always leaves `scripts/seed/restaurants.yml` byte-identical.

### Real run

```bash
RESY_API_KEY=… uv run python scripts/resolve_resy_venue_ids.py
# or one at a time while validating the endpoint:
RESY_API_KEY=… uv run python scripts/resolve_resy_venue_ids.py --slug carbone-nyc
```

> **The resolution endpoint is `[ASSUMED]`.** Research A4 could not verify
> `GET {RESY_API_BASE}/3/venue?url_slug={slug}&location=ny`. The script isolates the call
> in a single function (`_resolve_one`) carrying a `TODO(spike)` marker, so correcting the
> shape after your DevTools capture is a one-function edit. If the endpoint 404s, capture
> the real one from the Network panel while loading a restaurant page and correct that
> function before re-running.

The script writes the file through a temp file plus rename, so an interrupted run cannot
truncate the seed data, and it edits only the `resy_venue_id` lines — every comment block
in the YAML survives (T-03-13).

### Then

```bash
git diff scripts/seed/restaurants.yml     # review EVERY id before committing it
RESY_ENABLED=true make seed               # creates the Resy rows and the resy:{id} jobs
```

Verify a resolved id before trusting it: open `https://resy.com/cities/ny/<resy_url_slug>`
and confirm the venue name matches the `name` field of that YAML entry. An id that points
at the wrong restaurant is worse than a null one, because it looks like it works.

---

## Step 4 — Flip the switch

`RESY_ENABLED=false` is the default and it is load-bearing: while it is false the seed
creates no Resy row, enqueues no Resy job, and the poller never launches Chromium (D-63).
Set `RESY_ENABLED=true` in `.env` only after steps 1–3 are complete and reviewed.

## Completion checklist

- [ ] `RESY_API_KEY` captured and in `.env` (+ GCP Secret Manager)
- [ ] `/4/find` request shape and response body captured; `fixtures.py` corrected if it differs
- [ ] Auth token header name confirmed (`X-Resy-Auth-Token` vs `X-Resy-Universal-Auth`, A5)
- [ ] 3+ accounts captured into `RESY_ACCOUNTS_JSON` (`docs/admin-evidence/resy.md`)
- [ ] `scripts/resolve_resy_venue_ids.py` run; 31 numeric ids written and spot-checked
- [ ] `RESY_ENABLED=true`, `make seed` re-run, `resy:` members visible in `sched:polls`
- [ ] This banner changed from `pending-human` to `complete` with the date
