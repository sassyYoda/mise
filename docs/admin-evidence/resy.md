# Resy Pre-Authenticated Accounts

> **STATUS: pending-admin-action**
>
> This file is an evidence template. VAPID + HMAC_MGMT_SECRET_V1 have already
> been generated locally on 2026-04-22 and live in `.env` (gitignored).
> The Resy account capture is the remaining human-action step.
>
> **Why this is a template, not live evidence:** Resy account creation requires
> real email addresses, phone numbers, real names, and interactive CAPTCHAs.
> Cookie capture requires a supervised Chromium session with DevTools
> open — none of these are performable from a coding agent context.
>
> **Author action checklist:**
>
> - [ ] Three throwaway-but-real Resy accounts created
>       (real email, plausible-looking name, real phone — Resy will SMS-verify).
>       Recommended: `mise-scrape-1@<your-domain>`, `…-2`, `…-3` via a personal
>       email alias system.
> - [ ] Each account logged into resy.com in Chrome with DevTools open
> - [ ] For each account, cookies captured from DevTools → Application →
>       Cookies → resy.com. Minimum keys to capture:
>       `auth_token`, `resy_auth_token`, `_resy_session`. Capture ALL cookies
>       on the `resy.com` domain to be safe.
> - [ ] Cookies serialized as JSON into `.env` as `RESY_ACCOUNTS_JSON` —
>       format documented below.
> - [ ] `RESY_ACCOUNTS_JSON` mirrored into GCP Secret Manager
>       (`gcloud secrets create RESY_ACCOUNTS_JSON …` — see docs/admin-evidence/gcp.md)
> - [ ] Fields below filled
> - [ ] STATUS banner updated to `active`

---

- **Account count:** TODO — fill in once capture complete; must be >= 3
- **Storage locations:**
  - `.env` key `RESY_ACCOUNTS_JSON` (local dev, gitignored)
  - GCP Secret Manager secret name `RESY_ACCOUNTS_JSON` in project `mise-en-place-prod`
- **Cookie capture date:** TODO — YYYY-MM-DD
- **Cookie refresh cadence:** Re-capture if the poller starts seeing 401/403 responses from Resy (session expiry varies; community scrapers report 30–90 day lifetime). Track rotation incidents in a "Rotation log" below.

## Security convention (T-05 / D-24 / Pitfall 8)

**Resy session cookies are stored in two places only, never a third:**

1. `.env` — local dev only, file is in `.gitignore` line 138.
2. GCP Secret Manager — production runtime load path.

At runtime (Phase 3 onwards), cookies are loaded into **Playwright browser
context memory ONLY**. They are **NEVER** written to any database table,
never logged, never sent to any external service. This convention is
enforced by:

- `shared/telemetry.py::_redact_secrets` stripping `RESY_ACCOUNTS_JSON` from
  any log event dict (already in place as of Plan 01-01).
- Phase 3 poller code reviews MUST grep the diff for any line that writes
  a Resy cookie value to `session.execute`, `INSERT`, or similar.

See also Pitfall 8 in `.planning/research/PITFALLS.md` — persisting Resy
cookies to the DB would break the NY Restaurant Reservation Anti-Piracy
Act posture AND expose the accounts to DB dumps.

## RESY_ACCOUNTS_JSON format

```json
[
  {
    "email": "mise-scrape-1@your-domain.example",
    "cookies": {
      "auth_token": "ey…",
      "resy_auth_token": "…",
      "_resy_session": "…"
    }
  },
  {
    "email": "mise-scrape-2@your-domain.example",
    "cookies": { "…": "…" }
  },
  {
    "email": "mise-scrape-3@your-domain.example",
    "cookies": { "…": "…" }
  }
]
```

Stored as a single-line JSON string in `.env` (no line breaks inside the
value) so `dotenv` parses it cleanly. The poller uses `json.loads()` on
the env var.

## Capture procedure (detailed)

For each account:

1. Open Chrome (non-Incognito so session persists for capture).
2. Navigate to https://resy.com/login and log in with the account's email + password.
3. Open DevTools (Cmd+Option+I) → Application tab → Storage → Cookies → https://resy.com
4. Select all rows (Cmd+A) → right-click → Copy → Copy all as JSON (or use `document.cookie` from the Console and parse).
5. Reformat into the account object shape above (just the `auth_token` family of keys is sufficient; Playwright will refresh the rest on first request).
6. Append the account object to the `RESY_ACCOUNTS_JSON` array.
7. After all three accounts captured, update `.env` and mirror to GCP Secret Manager:

   ```bash
   gcloud secrets create RESY_ACCOUNTS_JSON --project=mise-en-place-prod \
     --replication-policy=automatic \
     --data-file=- <<< "$(grep '^RESY_ACCOUNTS_JSON=' .env | cut -d= -f2-)"
   ```

## Rotation log

| Date | Account | Reason | Re-captured by |
|------|---------|--------|----------------|
| TODO | TODO    | TODO   | TODO           |

## VAPID + HMAC secret generation (already complete)

- **VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY** — generated 2026-04-22 locally via
  `cryptography` SECP256R1 keypair, b64url-no-pad encoded. Present in `.env`.
  Pending GCP Secret Manager mirror after 01-03-T2.
- **HMAC_MGMT_SECRET_V1** — generated 2026-04-22 locally via
  `secrets.token_bytes(32).hex()` (64 hex chars = 32 bytes of entropy).
  Present in `.env`. Pending GCP Secret Manager mirror after 01-03-T2.

## Covers

- D-24 — Resy pre-authenticated accounts captured on Day 1 (>=3 required, FOUND-06)
- D-25 — VAPID keypair generated
- D-26 — HMAC_MGMT_SECRET_V1 generated (Named Symbol name exactly — NOT `HMAC_SECRET_V1`)
- T-05 / Pitfall 8 — cookies-in-memory-only convention stated verbatim
- FOUND-06 — Resy pre-auth accounts available for Phase 3 poller
