# Twilio A2P 10DLC Status

> **STATUS: pending-admin-action**
>
> This file is an evidence template. The human operator (@avahuja3) must complete the Twilio registration workflow described in
> [`docs/runbooks/twilio-10dlc-setup.md`](../runbooks/twilio-10dlc-setup.md) and fill in the fields below.
>
> **Why this is a template, not live evidence:** Twilio A2P 10DLC registration requires (a) submitting a credit card, (b) providing personal identity + business details, (c) accepting carrier-reviewed legal attestations. None of these are performable from a coding agent context. This task MUST start on Day 1 of Phase 1 because carrier approval has a 1–3 week lead time (Pitfall 5, D-21). SMS at Phase 4 (Week 5) will be broken if this is deferred.
>
> **Author action checklist** — tick each when complete:
>
> - [ ] Twilio account created; `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` captured into `.env`
> - [ ] Brand registered (Standard Brand) — Brand SID recorded below
> - [ ] Messaging Service created — `TWILIO_MESSAGING_SERVICE_SID` captured into `.env`
> - [ ] Standard Campaign registered — Campaign SID recorded below, status Pending or Registered
> - [ ] Primary 10DLC phone number purchased; SID + E.164 recorded below; also in `.env` as `TWILIO_FROM_NUMBER`
> - [ ] Toll-free backup number purchased + verification submitted; SID + E.164 recorded below; also in `.env` as `TWILIO_TOLLFREE_FROM_NUMBER`
> - [ ] Phone number attached to Messaging Service sender pool
> - [ ] Screenshot of Campaign Status page saved to `docs/admin-evidence/twilio-campaign-screenshot.png`
> - [ ] All five secrets copied into GCP Secret Manager once project `mise-en-place-prod` exists (Task 2)
> - [ ] This STATUS banner changed to `active` once all fields below are filled

**Submitted:** TODO: fill in ISO date (YYYY-MM-DD) once submitted

---

## Brand Registration

- **Brand SID:** `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — TODO: replace with real SID from Twilio Console → Messaging → Regulatory Compliance → A2P 10DLC → Brands
- **Brand Name:** TODO: fill in legal entity name submitted on the form
- **Brand Type:** Standard Brand (NOT Low Volume, NOT Sole Proprietor — D-21 + runbook Step 2)
- **Status:** Pending
- **Vetting fee paid:** TODO: $4 one-time — confirm charged

## Campaign Registration

- **Campaign SID:** `CMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — TODO: replace with real SID
- **Messaging Service SID:** `MGxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — TODO: replace with real SID (also copied into `.env` as `TWILIO_MESSAGING_SERVICE_SID`)
- **Use Case:** Low Volume Mixed (per runbook Step 3 — cheapest tier, sufficient for MVP)
- **Campaign description submitted:**
  > Mise en Place is a free restaurant reservation availability monitoring service. Users visit mise.place, select a restaurant they want to dine at, and submit their phone number to receive an SMS alert when a table becomes available due to a cancellation. Users explicitly opt in per restaurant and can unsubscribe at any time by replying STOP.
- **Opt-out keywords submitted:** `STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT`
- **Help keywords submitted:** `HELP, INFO`
- **Sample messages submitted:** 3 templates (per runbook Step 3) — each references `mise.place/go/{token}` and includes "Reply STOP to unsubscribe"
- **Status:** Pending
- **One-time + monthly fees paid:** TODO: confirm $10 one-time + $10/mo ongoing

## Phone Numbers

| Slot | E.164 | Twilio SID | Capability | Status |
|------|-------|------------|------------|--------|
| Primary 10DLC | `+1XXXXXXXXXX` — TODO | `PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — TODO | SMS (+ MMS optional) | Attached to Messaging Service sender pool: TODO yes/no |
| Toll-free backup | `+1XXXXXXXXXX` — TODO | `PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — TODO | SMS | Verification: Pending (TODO: update to Verified when cleared) |

## Evidence Artifacts

- **Campaign status screenshot:** `docs/admin-evidence/twilio-campaign-screenshot.png` — TODO: save screenshot from Twilio Console A2P 10DLC page
- **Brand approval email:** archive a copy in a personal email folder tagged `mise/admin`

## Link Back to Secrets

Once the five Twilio IDs above are captured, they MUST also land in:

1. **`.env`** (local dev, gitignored) — keys: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_MESSAGING_SERVICE_SID`, `TWILIO_FROM_NUMBER`, `TWILIO_TOLLFREE_FROM_NUMBER`
2. **GCP Secret Manager** in project `mise-en-place-prod` (Task 2 provisions the project) — same five keys, one secret per value

## Covers

- SC2 — Twilio A2P 10DLC Standard Campaign is in Pending or Registered status on Day 1 (this template satisfies the evidence-file shape; the actual "Pending" status requires author submission)
- FOUND-05 — Twilio A2P 10DLC / toll-free registration submitted on Day 1 of Week 1
- D-21 — Multi-week Twilio 10DLC approval clock starts on Day 1
- Pitfall 5 — Twilio 10DLC lead time mitigation

## Author Notes

Use this section to record rejection reasons, resubmission dates, and any carrier-specific feedback during the 1–3 week approval window.

- YYYY-MM-DD — TODO
