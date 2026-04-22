# Twilio 10DLC Setup — Day 1 Runbook

**Why this matters:** US phone carriers require business SMS senders to register before their texts go through reliably. Approval takes **1–3 weeks** and cannot be rushed. If Mise en Place's SMS is needed in Phase 4 (Week 5), registration **must** be submitted on Day 1 of Week 1. Skipping this means broken SMS at the portfolio-launch demo.

**Owner:** you
**Target submit date:** Day 1 of Phase 1
**Expected approval:** 1–3 weeks after submission
**Estimated cost:** ~$20–25/mo at MVP scale

---

## TL;DR

> Fill out two forms on twilio.com (**Brand** + **Campaign**) + buy a phone number. Wait. While waiting, also register a **toll-free number** as a backup path in case 10DLC is still pending at Week 5.

---

## Prerequisites (must be true before you start)

- [ ] `mise.place` domain purchased and pointing to **any** live page (even "Coming soon")
- [ ] A credit card for Twilio billing
- [ ] Decide: personal name vs LLC. Personal is fine for MVP — you can re-register under an LLC later
- [ ] Email address you'll use for Twilio (consider a dedicated one like `admin@mise.place`)
- [ ] Block 45 minutes of uninterrupted time

---

## Step 1 — Create Twilio account

1. Go to https://www.twilio.com/try-twilio
2. Sign up with your email
3. Verify your personal phone number (they send an SMS)
4. Answer the onboarding questions:
   - "What do you want to do first?" → **Send an SMS**
   - "Which language?" → **Python**
   - "Are you building for yourself or a company?" → **Myself** (or company if you have an LLC)
5. You land on the Twilio Console dashboard
6. **Save your Account SID and Auth Token** — put them in your password manager or GCP Secret Manager. They look like:
   ```
   ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
7. Add a payment method: **Admin → Billing → Manage Billing → Add Card**. Put $20 of trial credit on it.

---

## Step 2 — Register the Brand

The Brand = "who is sending the texts."

1. Left nav: **Messaging → Regulatory Compliance → A2P 10DLC**
2. Click **Register a Brand**
3. Pick **Standard Brand** (not Low Volume, not Sole Proprietor — even if you're solo, Standard gives better throughput)
4. Fill in:

   | Field | What to enter |
   |-------|---------------|
   | Legal business name | Your legal name OR LLC name |
   | Business type | Individual / Sole Proprietor (or LLC if you have one) |
   | Business industry | **Technology** |
   | Website URL | `https://mise.place` |
   | Business address | Your real address (required; not displayed publicly) |
   | Business phone | Your real phone |
   | EIN | Leave blank if no LLC; otherwise enter it |
   | Stock ticker | Skip |
   | Business email | `admin@mise.place` or similar |
   | Point of contact | Your name + email + phone |

5. **Submit.** Pay the one-time vetting fee (~$4). You'll see "Brand Status: PENDING" → usually clears to "VERIFIED" within minutes to a few hours.

---

## Step 3 — Register the Campaign

The Campaign = "what kind of texts you'll send."

1. From the A2P 10DLC page, click **Create Messaging Service** (if you don't already have one), then **Register a Campaign**
2. Pick **Use Case: Low Volume Mixed** (cheapest, fine for MVP — you can upgrade later when volume grows)
3. Fill in:

   **Campaign description (what you're doing):**
   ```
   Mise en Place is a free restaurant reservation availability monitoring service. Users visit mise.place, select a restaurant they want to dine at, and submit their phone number to receive an SMS alert when a table becomes available due to a cancellation. Users explicitly opt in per restaurant and can unsubscribe at any time by replying STOP.
   ```

   **Message flow (how users opt in):**
   ```
   Users visit mise.place, navigate to a specific restaurant page, click "Notify me when a table opens," enter their party size, date range, and phone number, and click "Create watch." A confirmation screen and a confirmation email state that SMS alerts will be sent when availability is detected. Users can unsubscribe at any time by replying STOP to any message or by visiting their management page. Consent is per-watch and is not shared with third parties.
   ```

   **Opt-in keywords:** leave default
   **Opt-out keywords:** `STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT`
   **Help keywords:** `HELP, INFO`

   **Help message (what users get when they text HELP):**
   ```
   Mise: reservation availability alerts. Reply STOP to unsubscribe. Questions: support@mise.place
   ```

   **Sample message 1 (must match real content):**
   ```
   Mise: Table for 2 at Carbone just opened for Fri 5/9 8:00pm. Book now: mise.place/go/abc123. Reply STOP to unsubscribe.
   ```

   **Sample message 2:**
   ```
   Mise: 3 tables opened at Lilia for Sat 5/10 (party of 4, 7-9pm). View: mise.place/go/def456. Reply STOP to stop.
   ```

   **Sample message 3:**
   ```
   Mise: Your watch for Rezdora (Sun 5/11, party 2) paused because the date passed. Re-enable: mise.place/manage/xyz. Reply STOP to stop.
   ```

4. Confirm boxes:
   - [x] Messages include opt-out language (STOP)
   - [x] Users have clearly opted in
   - [x] No age-gated / SHAFT content (Sex, Hate, Alcohol, Firearms, Tobacco)
   - [x] No affiliate marketing
   - [x] No URL shorteners except branded ones (mise.place/go/ is your own, that's fine)

5. **Submit.** Campaign review fee: ~$10 one-time + ~$10/mo ongoing. Status: **PENDING** → waits for carrier approval (this is the slow part — 1–3 weeks).

---

## Step 4 — Buy a phone number

1. **Phone Numbers → Manage → Buy a number**
2. Country: **United States**
3. Capabilities: ✅ SMS (✅ MMS optional)
4. Try to pick a NYC area code (212, 646, 917, 718) for vibe — not required
5. Price: **~$1/month**
6. **Buy number** — costs ~$1 charged to your account

Then attach it to the campaign:

1. **Messaging → Services → (your service) → Sender Pool**
2. **Add Senders → Phone Number** → select the one you bought

---

## Step 5 — Backup: Toll-Free Verification

Do this **in parallel** with the 10DLC registration. Toll-free usually approves in days instead of weeks. If 10DLC is still pending at Week 5, you launch SMS on the toll-free number.

1. **Phone Numbers → Buy a number** → filter by **Toll-Free** (`+1 (833)`, `(844)`, `(855)`, `(866)`, `(877)`, `(888)`)
2. Buy one (~$2/mo)
3. **Messaging → Regulatory Compliance → Toll-Free Verification → Submit Verification**
4. Fill in essentially the same content as the 10DLC Campaign above (use case, opt-in flow, sample messages)
5. Submit

---

## Step 6 — Save credentials

Put these in **GCP Secret Manager** (or `.env.local` for now, never commit):

```
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxx   # from the Messaging Service you created
TWILIO_FROM_NUMBER=+1917xxxxxxx            # your 10DLC number
TWILIO_TOLLFREE_FROM_NUMBER=+1833xxxxxxx   # backup
```

---

## Step 7 — Track approval status

Check once a week:

1. **Messaging → Regulatory Compliance → A2P 10DLC**
2. Look at **Campaign Status**:
   - `PENDING` → still in review, keep waiting
   - `VERIFIED` → 🎉 you're cleared to send
   - `FAILED` → read rejection reason, fix, resubmit (usually a sample-message or opt-in-flow issue)

**If rejected:** the most common reasons are:
- Sample message doesn't match stated use case
- Opt-in flow is vague ("users sign up" is too thin — include the actual UI steps)
- Website doesn't describe the SMS program
- STOP language missing from a sample message

Fix the form, resubmit — usually clears on the second try.

---

## Before you send your first real SMS

- [ ] Campaign Status = `VERIFIED`
- [ ] Phone number attached to the campaign
- [ ] Your code honors `STOP` / `UNSUBSCRIBE` via Twilio's `Messaging` webhook (Phase 4 implementation detail — NOTIF-04 in REQUIREMENTS.md)
- [ ] `mise.place` has a public privacy policy + terms page (carriers sometimes re-check during random audits)

---

## Cost summary at MVP scale (~2,500 SMS/day max)

| Item | Cost |
|------|------|
| Brand registration | ~$4 one-time |
| Campaign registration | ~$10 one-time |
| Campaign maintenance | ~$10/month |
| 10DLC phone number | ~$1/month |
| Toll-free number (backup) | ~$2/month |
| Per-SMS | ~$0.008 × ~75,000/mo max = ~$600/mo **worst case** |
| **Realistic MVP (actual send volume much lower)** | **~$20–30/month** |

At 50 restaurants × avg 8 events/day × small watchlist, real send volume will be closer to 200–500 SMS/day, not 2500.

---

## Links

- Twilio 10DLC overview: https://www.twilio.com/docs/messaging/compliance/a2p-10dlc
- Registration walkthrough: https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/onboarding
- Toll-free verification: https://www.twilio.com/docs/messaging/compliance/toll-free-message-verification
- Campaign use case guide: https://help.twilio.com/articles/1260803965530

---

*Covers REQ FOUND-05 (Twilio A2P 10DLC / toll-free registration submitted on Day 1 of Week 1). Gates Phase 4 (Notification Pipeline, REQ NOTIF-04).*
