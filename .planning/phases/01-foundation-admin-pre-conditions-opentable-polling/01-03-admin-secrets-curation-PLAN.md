---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 03
type: execute
wave: 3
depends_on: ["01"]
files_modified:
  - docs/runbooks/twilio-10dlc-setup.md
  - docs/admin-evidence/twilio-status.md
  - docs/admin-evidence/domain.md
  - docs/admin-evidence/gcp.md
  - docs/admin-evidence/resy.md
  - scripts/seed/restaurants.yml
  - .env
autonomous: false
requirements_addressed:
  - FOUND-03
  - FOUND-04
  - FOUND-05
  - FOUND-06

must_haves:
  truths:
    - "Twilio A2P 10DLC Standard Campaign is in 'Pending' or 'Registered' status in the Twilio console; toll-free number registered in parallel as backup (SC2)"
    - "`mise.place` domain is registered at a registrar of user's choice"
    - "GCP project `mise-en-place-prod` exists with Artifact Registry and Secret Manager APIs enabled"
    - "At least 3 Resy pre-authenticated accounts' cookies are stored in `.env` as `RESY_ACCOUNTS_JSON` and in GCP Secret Manager; convention 'cookies in Playwright context memory only, never in DB' is documented"
    - "VAPID keypair exists: `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` set in `.env` and GCP Secret Manager"
    - "`HMAC_MGMT_SECRET_V1` set in `.env` and GCP Secret Manager (generated from `secrets.token_bytes(32)`)"
    - "`scripts/seed/restaurants.yml` contains >= 50 NYC restaurants with all required fields"
  artifacts:
    - path: docs/admin-evidence/twilio-status.md
      provides: "Brand SID, Campaign SID, toll-free SID, and status screenshot reference (SC2)"
      contains: "Brand SID"
    - path: docs/admin-evidence/domain.md
      provides: "Registrar name, expiry, DNS provider"
      contains: "mise.place"
    - path: docs/admin-evidence/gcp.md
      provides: "GCP project ID record"
      contains: "mise-en-place-prod"
    - path: docs/admin-evidence/resy.md
      provides: "Resy account count (>=3) and storage locations"
      contains: "RESY_ACCOUNTS_JSON"
    - path: scripts/seed/restaurants.yml
      provides: "Hand-curated NYC restaurant catalog (>=50 entries)"
  key_links:
    - from: ".env"
      to: "GCP Secret Manager"
      via: "Secrets stored in both locations (D-09, D-24, D-25, D-26)"
      pattern: "VAPID_PRIVATE_KEY|HMAC_MGMT_SECRET_V1|RESY_ACCOUNTS_JSON"
    - from: "scripts/seed/restaurants.yml"
      to: "scripts/seed_restaurants.py"
      via: "YAML seed file read by seed script (D-15)"
      pattern: "opentable_rid"
---

<objective>
Complete all Day-1 admin pre-conditions: Twilio A2P 10DLC registration, domain registration, GCP project provisioning, Resy account capture, VAPID + HMAC secret generation, and hand-curation of 50 NYC restaurants. These are human-executed tasks — not automatable. This plan runs in parallel with Plan 04.

Purpose: The multi-week Twilio 10DLC approval clock MUST start on Day 1 (Pitfall 5, D-21). All other secrets and the restaurant catalog are gates for Plan 05 (poller service). SC2 and SC3 are fully delivered by this plan.

Output: Evidence files in `docs/admin-evidence/`, secrets in `.env` + GCP Secret Manager, `scripts/seed/restaurants.yml` with >=50 entries.
</objective>

<execution_context>
@/Users/aryanahuja/projects/mise/.claude/get-shit-done/workflows/execute-plan.md
@/Users/aryanahuja/projects/mise/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md
@docs/runbooks/twilio-10dlc-setup.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-01-SUMMARY.md
</context>

<tasks>

<task id="01-03-T1" type="checkpoint:human-action">
  <name>Task 1: Twilio A2P 10DLC Standard Campaign registration (Day-1 clock start — SC2)</name>
  <read_first>
    docs/runbooks/twilio-10dlc-setup.md (full runbook — follow step by step),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-21),
    .planning/research/PITFALLS.md (Pitfall 5 — Twilio 10DLC lead time)
  </read_first>
  <action>
CRITICAL: This task starts the multi-week Twilio carrier approval clock. SMS will not work in Phase 4 unless this is submitted on Day 1. Do not defer.

Follow docs/runbooks/twilio-10dlc-setup.md step by step to:

1. Log in to the Twilio Console (twilio.com/console)
2. Navigate to Messaging > Regulatory Compliance > A2P 10DLC > Brands
3. Submit a Standard Campaign (not Low Volume Mixed) with:
   - Use case: "Notifications" — matches the user-facing copy in the opt-in flow on mise.place
   - Description must state: "User-initiated restaurant availability alerts. Users opt in by submitting their phone number on mise.place and confirming an HMAC-signed management link. Opt-out via reply STOP."
   - Include opt-out (STOP keyword) and opt-in documentation exactly as described in runbook
4. Purchase a US long-code (10DLC) phone number
5. Register a toll-free number IN PARALLEL as backup
6. Record the following in docs/admin-evidence/twilio-status.md:

```
# Twilio A2P 10DLC Status

**Submitted:** [date]

## Brand Registration
- Brand SID: ACxxxxxxxx (fill in)
- Brand Name: [fill in]
- Status: [Pending / Registered]

## Campaign Registration
- Campaign SID: [fill in]
- Use Case: [fill in]
- Status: [Pending / Registered]

## Phone Numbers
- Primary 10DLC number: +1xxxxxxxxxx (SID: PNxxxxxxxx)
- Toll-free backup: +1xxxxxxxxxx (SID: PNxxxxxxxx)
- Toll-free verification status: [Pending / Verified]

## Screenshot
- Screenshot of Campaign status page saved to docs/admin-evidence/twilio-campaign-screenshot.png
```

Store TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_MESSAGING_SERVICE_SID in .env.
  </action>
  <acceptance_criteria>
    - `grep -q "Brand SID" docs/admin-evidence/twilio-status.md`
    - `grep -q "Campaign SID" docs/admin-evidence/twilio-status.md`
    - `grep -q "Pending\|Registered" docs/admin-evidence/twilio-status.md`
    - `grep -q "TWILIO_ACCOUNT_SID" .env`
  </acceptance_criteria>
</task>

<task id="01-03-T2" type="checkpoint:human-action">
  <name>Task 2: Domain registration and GCP project provisioning</name>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-22, D-23)
  </read_first>
  <action>
Domain registration:
Register mise.place at your preferred registrar (Namecheap, Cloudflare Registrar, Porkbun, or Google Domains).

Record in docs/admin-evidence/domain.md:
```
# Domain Registration

- Domain: mise.place
- Registrar: [fill in]
- Registered date: [fill in]
- Expiry date: [fill in]
- DNS provider: [fill in — Cloudflare DNS recommended for Phase 7]
- Auto-renew: [yes/no]
```

GCP project provisioning:
Run these commands (install gcloud CLI first if not present):

  gcloud projects create mise-en-place-prod --name="Mise en Place" --set-as-default
  gcloud services enable artifactregistry.googleapis.com --project=mise-en-place-prod
  gcloud services enable secretmanager.googleapis.com --project=mise-en-place-prod
  gcloud services list --project=mise-en-place-prod --filter="config.name:(artifactregistry OR secretmanager)" --format="table(config.name,state)"

Record in docs/admin-evidence/gcp.md:
```
# GCP Project

- Project ID: mise-en-place-prod
- APIs enabled:
  - artifactregistry.googleapis.com
  - secretmanager.googleapis.com
- Created: [date]
- Billing account linked: [yes/no]
- Note: Terraform IaC deferred to Phase 7. No resources except project + APIs at P1.
```
  </action>
  <acceptance_criteria>
    - `grep -q "mise.place" docs/admin-evidence/domain.md`
    - `grep -q "mise-en-place-prod" docs/admin-evidence/gcp.md`
    - `grep -q "artifactregistry.googleapis.com" docs/admin-evidence/gcp.md`
    - `grep -q "secretmanager.googleapis.com" docs/admin-evidence/gcp.md`
    - `gcloud projects describe mise-en-place-prod --format="value(projectId)" 2>/dev/null | grep -q "mise-en-place-prod"`
    - `gcloud services list --project=mise-en-place-prod --format="value(config.name)" 2>/dev/null | grep -q "artifactregistry.googleapis.com"`
    - `gcloud services list --project=mise-en-place-prod --format="value(config.name)" 2>/dev/null | grep -q "secretmanager.googleapis.com"`
  </acceptance_criteria>
</task>

<task id="01-03-T3" type="checkpoint:human-action">
  <name>Task 3: Resy accounts capture, VAPID keypair, HMAC secret generation</name>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-24, D-25, D-26),
    .planning/research/PITFALLS.md (Pitfall 8 — never persist Resy cookies to DB)
  </read_first>
  <action>
Resy pre-authenticated accounts (>=3 accounts required, D-24, FOUND-06):

For each Resy account:
1. Log in to resy.com in Chrome with DevTools open
2. After login, open DevTools > Application > Cookies > resy.com
3. Copy all cookie key/value pairs
4. Encode as JSON array:
   [{"email":"user@example.com","cookies":{"auth_token":"...","resy_auth_token":"..."}}, ...]
5. Store as RESY_ACCOUNTS_JSON in .env
6. Store in GCP Secret Manager:
   echo -n '[...]' | gcloud secrets create RESY_ACCOUNTS_JSON --data-file=- --project=mise-en-place-prod

SECURITY CONVENTION (T-05, D-24, Pitfall 8): Resy session cookies are stored in .env (local dev) and GCP Secret Manager (production) ONLY. They are NEVER written to any database table. Playwright context memory only during Phase 3 runtime.

Record in docs/admin-evidence/resy.md:
```
# Resy Pre-Authenticated Accounts

- Account count: [fill in — must be >= 3]
- Storage locations:
  - .env RESY_ACCOUNTS_JSON (local dev, gitignored)
  - GCP Secret Manager: RESY_ACCOUNTS_JSON in project mise-en-place-prod
- Cookie capture date: [fill in]
- Convention: Cookies live in Playwright context memory ONLY during Phase 3 runtime. NEVER written to any database table (T-05, Pitfall 8).
```

VAPID keypair generation (D-25):

  uv run python -c "
from pywebpush import Vapid
import base64
v = Vapid()
v.generate_keys()
print('VAPID_PUBLIC_KEY=' + base64.urlsafe_b64encode(v.public_key.public_bytes_raw()).decode())
print('VAPID_PRIVATE_KEY=' + base64.urlsafe_b64encode(v.private_key.private_bytes_raw()).decode())
"

Copy VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY into .env.
Store both in GCP Secret Manager:
  gcloud secrets create VAPID_PUBLIC_KEY --data-file=- --project=mise-en-place-prod <<< "$VAPID_PUBLIC_KEY"
  gcloud secrets create VAPID_PRIVATE_KEY --data-file=- --project=mise-en-place-prod <<< "$VAPID_PRIVATE_KEY"

HMAC secret generation (D-26):
  HMAC_SECRET=$(uv run python -c "import secrets; print(secrets.token_bytes(32).hex())")

Copy HMAC_MGMT_SECRET_V1=$HMAC_SECRET into .env.
Store in GCP Secret Manager:
  gcloud secrets create HMAC_MGMT_SECRET_V1 --data-file=- --project=mise-en-place-prod <<< "$HMAC_SECRET"
  </action>
  <acceptance_criteria>
    - `grep -q "RESY_ACCOUNTS_JSON" docs/admin-evidence/resy.md`
    - `grep -q "Account count" docs/admin-evidence/resy.md`
    - `grep -q "VAPID_PUBLIC_KEY" .env`
    - `grep -q "VAPID_PRIVATE_KEY" .env`
    - `grep -q "HMAC_MGMT_SECRET_V1" .env`
    - `grep -q "RESY_ACCOUNTS_JSON" .env`
    - HMAC_MGMT_SECRET_V1 value in .env must be 64 hex characters (32 bytes)
  </acceptance_criteria>
</task>

<task id="01-03-T4" type="checkpoint:human-action">
  <name>Task 4: Hand-curate 50 NYC restaurants into scripts/seed/restaurants.yml (SC3 — 4-6 hours)</name>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-14, D-15, D-16),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (Specifics — seed restaurant sources)
  </read_first>
  <action>
Estimated work time: 4-6 hours. This is the SC3 gate (>=50 restaurants required for P1 exit).

Curate at least 50 NYC restaurants from these public lists:
- Eater NYC Essential 38: eater.com/maps/best-restaurants-nyc-38
- Infatuation NYC Hit List: theinfatuation.com/new-york/guides/the-nyc-hit-list
- Resy Top Reserved NYC: resy.com/cities/ny (sort by most reserved)
- OpenTable Best of NYC: opentable.com/best-restaurants (filter NYC)

For each restaurant, create one YAML entry. All 7 fields with data are required (D-16):

```yaml
# scripts/seed/restaurants.yml
# Hand-curated from Eater NYC Essential 38, Infatuation Hit List,
# Resy Top Reserved NYC, OpenTable Best of NYC.
# D-14, D-15, D-16: all required fields populated. "The tables everyone wants."

restaurants:
  - name: "Carbone"
    slug: "carbone-nyc"
    neighborhood: "Greenwich Village"
    cuisine: "Italian-American"
    price_tier: 4
    cover_photo_url: "https://example.com/carbone.jpg"
    opentable_rid: 12345
    resy_venue_id: "carbone-new-york-new-york"

  # ... 49 more entries
```

How to find OpenTable RID: Visit the restaurant's OpenTable page in Chrome DevTools > Network > filter "availability" > look for rid= parameter. Or the URL often contains /r/restaurant-name?rid=12345.

How to find Resy venue_id: The Resy URL format is resy.com/cities/ny/{venue_id}/ — the last path segment. If not on Resy, set resy_venue_id to null.

Aim for geographic diversity (SoHo, Tribeca, West Village, East Village, Midtown, LES, Williamsburg) and cuisine diversity (Italian, Japanese, French, New American, Seafood, Steakhouse, Mexican, Korean).

Commit scripts/seed/restaurants.yml when complete.
  </action>
  <acceptance_criteria>
    - `python3 -c "import yaml; r=yaml.safe_load(open('scripts/seed/restaurants.yml')); entries=r['restaurants']; assert len(entries) >= 50, f'Only {len(entries)}'; required=['name','slug','neighborhood','cuisine','price_tier','cover_photo_url','opentable_rid']; [exit(f'Missing {f} in {e[\"name\"]}') for e in entries for f in required if e.get(f) is None]; print(f'OK: {len(entries)} restaurants')" 2>&1 | grep -q "OK:"`
  </acceptance_criteria>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| .env -> git | Secret values in .env must never cross into git history |
| Resy cookies -> database | Session cookies stay in Playwright context memory only, never in any DB table |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01 | Information Disclosure | .env secrets / git history | mitigate | All secrets (TWILIO_AUTH_TOKEN, HMAC_MGMT_SECRET_V1, VAPID_PRIVATE_KEY, RESY_ACCOUNTS_JSON) stored only in .env (gitignored per D-09) and GCP Secret Manager; .env.example has placeholder values only; .gitignore entry for .env verified in Plan 01 |
| T-05 | Information Disclosure | Resy session cookies | mitigate | Convention documented in docs/admin-evidence/resy.md: cookies in Playwright context memory ONLY during Phase 3 runtime; NEVER written to any database table; Phase 3 implementation enforces this; convention stated verbatim in docs/admin-evidence/resy.md for Phase 3 implementers |
</threat_model>

<verification>
After all four tasks complete:

```bash
# SC2: Twilio evidence exists
grep -q "Brand SID" docs/admin-evidence/twilio-status.md && echo "SC2 Twilio OK"
grep -q "Campaign SID" docs/admin-evidence/twilio-status.md && echo "Campaign OK"

# Domain + GCP evidence
grep -q "mise.place" docs/admin-evidence/domain.md && echo "domain OK"
grep -q "mise-en-place-prod" docs/admin-evidence/gcp.md && echo "GCP OK"

# Resy evidence
grep -q "Account count" docs/admin-evidence/resy.md && echo "resy OK"

# Secrets in .env (values must not equal placeholder)
grep -q "VAPID_PUBLIC_KEY" .env && grep "VAPID_PUBLIC_KEY" .env | grep -v "your_vapid" && echo "VAPID OK"
grep -q "HMAC_MGMT_SECRET_V1" .env && grep "HMAC_MGMT_SECRET_V1" .env | grep -v "your_32" && echo "HMAC OK"
grep -q "RESY_ACCOUNTS_JSON" .env && echo "RESY OK"

# SC3: >= 50 restaurants, all fields
python3 -c "
import yaml
r = yaml.safe_load(open('scripts/seed/restaurants.yml'))
entries = r['restaurants']
assert len(entries) >= 50, f'Only {len(entries)} restaurants'
required = ['name','slug','neighborhood','cuisine','price_tier','cover_photo_url','opentable_rid']
for e in entries:
    for f in required:
        assert e.get(f) is not None, f'Missing {f} in {e[\"name\"]}'
print(f'SC3 OK: {len(entries)} restaurants, all fields present')
"
```
</verification>

<success_criteria>
- docs/admin-evidence/twilio-status.md contains Brand SID, Campaign SID, status Pending or Registered — SC2 gate satisfied
- docs/admin-evidence/domain.md records registrar, expiry, DNS provider for mise.place
- docs/admin-evidence/gcp.md confirms mise-en-place-prod project exists with both APIs enabled
- docs/admin-evidence/resy.md confirms >= 3 accounts, storage locations, and cookie-in-memory-only convention stated
- .env contains non-placeholder values for VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, HMAC_MGMT_SECRET_V1, RESY_ACCOUNTS_JSON, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
- HMAC_MGMT_SECRET_V1 is 64 hex characters (32 bytes from secrets.token_bytes(32))
- scripts/seed/restaurants.yml contains >= 50 restaurants with all 7 required fields non-null — SC3 gate (YAML side) satisfied
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-03-SUMMARY.md`
</output>
