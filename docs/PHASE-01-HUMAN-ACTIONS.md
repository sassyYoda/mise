# Phase 01 — What You Need To Do (Step by Step)

**Read me first.** Phase 01 is code-complete, but six things in the real world need *you* to do them before Phase 01 can actually close and Phase 02 can start. This file explains each one in plain English and in the order you should do them.

**Total time you'll spend:** ~4 hours of active work + ~1–3 weeks of waiting (mostly Twilio carrier review running in the background).

---

## The big picture (30 seconds)

The app needs four things from the real world:

1. **A phone number that can send SMS** → Twilio wants proof you're a real business
2. **A website address (domain)** → for links in notifications, for Twilio to point at, and for email
3. **A Google Cloud project** → for deploying later and for storing secrets safely
4. **Resy login cookies** → the app books Resy on your behalf using these cookies

Then two technical checks:

5. **Capture OpenTable's real API URL** → we wrote the code with a placeholder; you have to confirm the real one by opening Chrome DevTools
6. **Run the poller for 24 hours** → to prove it hits ≥99% success rate in every hourly bucket (this is the PERF-02 requirement)

Some of these have long wait times, so start them in the right order.

---

## Priority / Order (do them in this sequence)

| # | Task | Active time | Wait time | Blocks |
|---|------|-------------|-----------|--------|
| 1 | Buy `mise.place` domain | 15 min | — | Twilio (needs website), Resend email |
| 2 | Submit Twilio 10DLC registration | 45 min | **1–3 weeks** | Phase 4 SMS (not Phase 1) |
| 3 | Create GCP project | 30 min | — | Phase 7 deploy (not Phase 1) |
| 4 | Capture OpenTable API URL (DevTools spike) | 30 min | — | PERF-02 24h run, Phase 2+ |
| 5 | Create 3 Resy accounts + capture cookies | 1 hour | — | Phase 3 (not Phase 1) |
| 6 | Run 24h PERF-02 observation | 5 min setup + 24h wait | 24 hours | Phase 01 close |

**Phase 01 close = tasks 1, 4, and 6 done** (domain, DevTools spike, 24h run). Tasks 2, 3, 5 have long timers but don't block Phase 01 itself — they block later phases, so start them now so they bake while you move forward.

---

## Task 1 — Buy the `mise.place` domain (15 min, do this first)

**Why:** Twilio needs a website to verify you're a real business. Resend needs a domain to send email from. Everything else waits on this.

**What to do:**

1. Go to **https://dash.cloudflare.com/?to=/:account/registrar** (Cloudflare Registrar — cheapest, no upsells).
2. Search for `mise.place`.
3. Buy it (usually ~$10–15/year for `.place`).
4. While still in Cloudflare, click **Websites → Add site → mise.place** (free plan is fine).
5. Create a super basic "Coming soon" page — anything works. Options:
   - **Easiest:** Cloudflare Pages (free). Click `Workers & Pages → Create → Pages → Direct Upload`, drop in an `index.html` that just says "Mise en Place — coming soon."
   - **Fine too:** point the A record to any static host you already have.
6. Verify you can visit `https://mise.place` and see something.

**Then update the evidence file:**

Open `docs/admin-evidence/domain.md` and replace the `STATUS: pending-admin-action` header with `STATUS: complete` and fill in:
- Registrar (`Cloudflare Registrar`)
- Purchase date
- Expiry date
- A screenshot of the live "Coming soon" page saved as `docs/admin-evidence/domain-live.png`

**Then do Resend email (10 more min):**

1. Go to **https://resend.com** → sign up with your `mise.place` email (or any email — you can change it later).
2. Click **Domains → Add domain → `mise.place`**.
3. Resend gives you 3 DNS records (SPF, DKIM, DMARC). Copy them.
4. Back in Cloudflare, go to your `mise.place` site → **DNS → Records → Add record** for each of the 3.
5. Click **Verify** in Resend. Should go green within a few minutes.
6. Generate a Resend API key. Copy it.
7. In your local `.env` file, set `RESEND_API_KEY=re_xxx`.

✅ Done with Task 1.

---

## Task 2 — Submit Twilio 10DLC registration (45 min active, 1–3 weeks wait)

**Why:** US phone carriers (Verizon, AT&T, T-Mobile) block SMS from unregistered senders. This registration is the legal paperwork that unblocks you. Approval is **1–3 weeks** and cannot be rushed. If you don't submit this today, Phase 4 SMS won't work.

**Full step-by-step is already written for you:** open `docs/runbooks/twilio-10dlc-setup.md`. It has screenshots of what to click. Follow it start to finish.

**Short version of what you'll do:**

1. Create Twilio account at **https://www.twilio.com/try-twilio**.
2. Add $20 credit (credit card required).
3. Fill out the **Brand Registration** form (company info — "personal/sole proprietor" is fine if you don't have an LLC).
4. Fill out the **Campaign Registration** form (describes what your messages will say — copy from the runbook's template).
5. Buy a US phone number (~$1/mo).
6. Also register a **toll-free number** as a backup in case 10DLC is still pending at Week 5.

**Then update evidence:**

Open `docs/admin-evidence/twilio-status.md` and fill in:
- Account SID
- Brand SID + status (likely `PENDING_REVIEW` for the next 1–3 weeks)
- Campaign SID + status
- Phone number you bought
- Toll-free number SID + status

**After submitting:** check back once a week. When status flips to `VERIFIED`, update the evidence file.

✅ Done with Task 2 (active portion). Now it bakes in the background.

---

## Task 3 — Create GCP project (30 min)

**Why:** Later phases deploy to Google Cloud Run, store production secrets in Secret Manager, and push Docker images to Artifact Registry. You don't need to deploy now, but you need the project to exist so Phase 7 isn't blocked.

**What to do:**

1. Go to **https://console.cloud.google.com/** → sign in with a Google account (a dedicated one is cleaner, e.g., `<your-email>+mise@gmail.com` — Gmail treats the `+` suffix as the same inbox but it's a distinct identity).
2. Click the project dropdown at the top → **New Project**.
3. Name it `mise-en-place-prod`. Project ID will auto-generate (usually `mise-en-place-prod` or with a number suffix — note what it picks).
4. Set up billing — link a credit card. GCP gives you $300 free credit for 90 days, which will cover you well past Phase 7.
5. Enable 3 APIs. Go to **APIs & Services → Library**, search for and enable each one:
   - **Artifact Registry API**
   - **Secret Manager API**
   - **Cloud Run API** (not used yet, but enable now so Phase 7 doesn't hit surprises)
6. Create an Artifact Registry repo:
   - **Artifact Registry → Create Repository**
   - Format: `Docker`
   - Mode: `Standard`
   - Region: `us-east1` (closest to NYC restaurants)
   - Name: `mise-docker`
7. Mirror your local secrets to Secret Manager:
   - Go to **Security → Secret Manager → Create Secret**.
   - Create one secret per key from your local `.env`. Start with these (read the values out of your local `.env`):
     - `HMAC_MGMT_SECRET_V1`
     - `VAPID_PRIVATE_KEY`
     - `VAPID_PUBLIC_KEY`
     - (Twilio SID/token and Resend key come later — once Task 1 and Task 2 finish)

**Then update evidence:**

Open `docs/admin-evidence/gcp.md` and fill in:
- GCP Project ID
- Artifact Registry path (e.g., `us-east1-docker.pkg.dev/mise-en-place-prod/mise-docker`)
- List of secrets created in Secret Manager
- A screenshot of the Secret Manager list saved as `docs/admin-evidence/gcp-secrets.png`

✅ Done with Task 3.

---

## Task 4 — Capture OpenTable's real API URL (30 min) ⭐ **BLOCKS PHASE 01 CLOSE**

**Why:** We wrote the OpenTable adapter with a placeholder URL because the real one can only be discovered by watching a live browser session. Without the real URL, the poller hits a dead endpoint and Task 6 (PERF-02) will fail.

**What you're actually doing:** opening Chrome DevTools, searching for a restaurant on opentable.com, watching the Network tab, and copying the exact request the website makes.

**Step-by-step:**

1. Open **Google Chrome** (not Safari — DevTools is friendlier in Chrome).
2. Open a new **Incognito window** (`Cmd-Shift-N`) — this avoids cached cookies messing with the capture.
3. In the incognito window, press `Cmd-Option-I` to open DevTools. Click the **Network** tab.
4. In the filter bar at the top of the Network tab, type `graphql` (this filters out noise).
5. Make sure the **Preserve log** checkbox is checked.
6. Now go to **https://www.opentable.com/s**.
7. Search for `"Le Bernardin"`, pick any date (e.g., tomorrow), party size 2.
8. After the availability page loads, look at the Network tab. You'll see one or more `graphql` requests. Click the one whose **Response** tab shows restaurant availability data (ignore `graphql` requests for search suggestions, reviews, etc.).
9. From the request's **Headers** tab, copy these things:
   - **Request URL** (looks like `https://www.opentable.com/dapi/fe/gql?optype=query&opname=RestaurantsAvailability`)
   - Full **Request Headers** block (all of it — paste into a scratchpad)
   - The **Request Payload** / **Query String Parameters** / **Body** (the full GraphQL query + variables)
10. From the request's **Response** tab, copy the full JSON response. Paste it into `OPENTABLE_SUCCESS_RESPONSE` in `services/poller/sources/opentable/fixtures.py` (replacing the placeholder fixture).

**Now update the code:**

1. Open `services/poller/sources/opentable/graphql.py`.
2. Find the line `OPENTABLE_GQL_ENDPOINT = "..."` with the `[ASSUMED]` comment.
3. Replace the URL with the one you captured.
4. Find the `build_request(...)` function. Compare its GraphQL query string to the one you captured. Update the query string, variable names, and required fields to match what OpenTable actually sent.
5. Open `services/poller/sources/opentable/README.md`. Find the `<!-- TODO(spike): -->` markers. Delete the markers and replace the placeholder values with the real ones you captured (endpoint, headers, query shape, rate limits you observed).
6. Run: `uv run pytest tests/unit/test_http_client_singleton.py tests/unit/test_ua_rotation.py tests/integration/test_poller_smoke.py -v`. The smoke test uses `respx` to mock the endpoint, so it should still pass with the real URL.

**Then backfill the restaurant YAML (10 min):**

The seed file `scripts/seed/restaurants.yml` has 55 NYC restaurants but each has `opentable_rid: TODO(01-05 spike)`. Now that you know the real endpoint:

1. For each restaurant, search for it on opentable.com.
2. The URL will be `https://www.opentable.com/r/<slug>` — click through and open DevTools. The restaurant's numeric `rid` appears in the GraphQL request payload as something like `"rid": 12345`.
3. Fill in that number into `scripts/seed/restaurants.yml` under that restaurant's `opentable_rid` field.
4. While you're there, grab the hero photo URL and fill in `cover_photo_url`.

This takes a while (~1 min/restaurant × 55 = ~1 hour). You can do a first pass with just the top 10 restaurants and come back for the rest later.

✅ Done with Task 4.

---

## Task 5 — Create 3 Resy accounts + capture cookies (1 hour, Phase 3 blocker)

**Why:** Resy (unlike OpenTable) requires you to be logged in to see availability. We bypass bot detection by rotating between 3 pre-authenticated sessions. This isn't needed for Phase 01 — it blocks Phase 03 — but you can knock it out now.

**Full step-by-step is already written:** open `docs/admin-evidence/resy.md`. It has detailed instructions for each step.

**Short version:**

1. Create 3 Resy accounts with 3 different email addresses. Use Gmail's `+suffix` trick to avoid needing real separate inboxes:
   - `<your-email>+mise1@gmail.com`
   - `<your-email>+mise2@gmail.com`
   - `<your-email>+mise3@gmail.com`
2. For each account:
   - Sign up at **https://resy.com**
   - Verify the email (Gmail routes all three to your main inbox)
   - Complete profile (first/last name, phone number, credit card on file)
3. For each account, capture cookies:
   - Log in to Resy in an **incognito window**
   - Open DevTools → **Application tab → Cookies → https://resy.com**
   - Copy every cookie (especially `auth_token` or similar)
4. Build the `RESY_ACCOUNTS_JSON` string. It's a JSON array of 3 objects:
   ```json
   [
     {"email": "<your-email>+mise1@gmail.com", "cookies": {"auth_token": "...", "_ga": "..."}},
     {"email": "<your-email>+mise2@gmail.com", "cookies": {...}},
     {"email": "<your-email>+mise3@gmail.com", "cookies": {...}}
   ]
   ```
5. Paste it (as a single line, JSON-escaped) into your local `.env` as `RESY_ACCOUNTS_JSON=[...]`.
6. Also set `RESY_ACCOUNT_1_EMAIL`, `RESY_ACCOUNT_1_PASSWORD`, ..._2_, ..._3_ (for re-login if cookies expire).

**Critical rule:** never commit `.env`. Never print these cookies in logs. The redaction code in `shared/telemetry.py` already strips them automatically, but don't paste them into chat windows either.

**Then update evidence:**

Open `docs/admin-evidence/resy.md` and mark which accounts are captured. Do NOT paste cookie values into this file — just note "3 accounts captured on YYYY-MM-DD, values in local `.env` only."

✅ Done with Task 5.

---

## Task 6 — Run the 24h PERF-02 observation (5 min setup + 24h wait) ⭐ **BLOCKS PHASE 01 CLOSE**

**Why:** PERF-02 is one of the phase requirements: *the poller must hit ≥99% success rate in every hourly bucket over a 24-hour run.* We wrote the code and the measurement script. You just have to run it and let it breathe for a full day.

**Prerequisites** (all must be done first):
- [x] Task 1 done (domain)
- [x] Task 4 done (DevTools spike — poller actually works now)
- [x] Docker Desktop running on your laptop
- [x] Your laptop plugged in and set to not sleep (System Settings → Battery → Prevent auto-sleep)

**The full runbook is already written:** open `docs/runbooks/perf02-24h-log.md`. It lists exact commands and has a log table you fill in hour-by-hour.

**Short version:**

1. Boot infra:
   ```bash
   cd <path-to-your-mise-checkout>
   docker compose -f ops/docker-compose.yml up -d
   ```
   Wait ~30 seconds for Kafka/Postgres healthchecks to pass.
2. Apply migrations + create topics:
   ```bash
   make migrate
   make topics
   ```
3. Seed restaurants:
   ```bash
   make seed
   ```
4. Start the poller in a detached tmux session so it survives you closing your laptop lid:
   ```bash
   tmux new -d -s poller 'uv run python -m services.poller 2>&1 | tee docs/runbooks/perf02-poller.log'
   ```
5. Record the start time (`t0`) and the poller's file descriptor count baseline in the runbook log:
   ```bash
   date -u +"%Y-%m-%dT%H:%M:%SZ"           # copy into log as t0
   lsof -p $(pgrep -f services.poller) | wc -l    # copy into log as FD baseline
   ```
6. **Wait 24 hours.** Peek every few hours: `tmux attach -t poller` (then `Ctrl-B D` to detach without killing).
7. After 24h, run the gate:
   ```bash
   make verify-perf02
   ```
   Exit code `0` = PASS (every hourly bucket ≥99%). Exit code `1` = FAIL (at least one bucket <99%). Exit code `2` = not enough data.
8. Fill in the log table in `docs/runbooks/perf02-24h-log.md` with the actual success-rate output.
9. If PASS: commit the filled-in runbook and update `docs/admin-evidence/` as appropriate.
10. If FAIL: look at `poll_log` rows where `status != 'success'`, fix whatever the error pattern shows (usually the OpenTable query shape is wrong — go back to Task 4), then restart the 24h run.

✅ Done with Task 6. **Phase 01 is now fully closed.** Ready for `/gsd-plan-phase 2`.

---

## Final checklist — Phase 01 close

Copy-paste this into a notes app and tick off as you go:

- [ ] Task 1 — `mise.place` bought + Coming Soon page live + Resend DNS verified → `docs/admin-evidence/domain.md` updated
- [ ] Task 2 — Twilio Brand + Campaign submitted → `docs/admin-evidence/twilio-status.md` updated (status = `PENDING_REVIEW` is fine)
- [ ] Task 3 — GCP project created + 3 APIs enabled + Artifact Registry repo + 3 secrets mirrored → `docs/admin-evidence/gcp.md` updated
- [ ] Task 4 — OpenTable endpoint captured, `graphql.py` + `README.md` + `fixtures.py` updated, at least top 10 `opentable_rid` values backfilled in `scripts/seed/restaurants.yml`
- [ ] Task 5 — 3 Resy accounts created + cookies captured → `.env` has `RESY_ACCOUNTS_JSON` + `RESY_ACCOUNT_[1-3]_*`
- [ ] Task 6 — 24h run executed → `make verify-perf02` exits 0 → `docs/runbooks/perf02-24h-log.md` filled in

When all 6 are ticked, come back to Claude Code and say **"Phase 01 done, plan Phase 02"** and we'll pick up from there.

---

## Things that can go wrong

| Problem | What to do |
|---------|------------|
| Twilio brand stuck `PENDING_REVIEW` > 3 weeks | Open a Twilio support ticket. Don't panic — carriers are slow. |
| Cloudflare DNS verification for Resend fails | Give it 15 more minutes (DNS propagation), then retry. If still failing, double-check you copied each record's type (TXT/CNAME) correctly. |
| DevTools Network tab shows no `graphql` request | OpenTable sometimes routes through a different endpoint shape. Change the filter to `opentable.com` and scan for the request whose Response contains `"availability"` or `"slots"`. |
| `make verify-perf02` exits 2 (not enough data) | You either didn't run the poller for a full 24h or the poller wasn't actually hitting OpenTable. Check `docker compose logs poller` and `tmux attach -t poller`. |
| Docker Desktop eats all my disk space | Run `docker system prune -a --volumes` after the 24h run completes. Frees up ~10 GB. |

If stuck: you can paste any error or screenshot back into Claude Code and ask for help on that specific step.
