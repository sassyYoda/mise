# Domain Registration

> **STATUS: pending-admin-action**
>
> This file is an evidence template. The human operator must register
> `mise.place` at their preferred registrar and fill in the fields below.
>
> **Why this is a template, not live evidence:** Domain purchase requires a
> credit card and registrar account, neither of which is performable from a
> coding agent context.
>
> **Recommended registrars (in rough order of preference):**
> 1. **Cloudflare Registrar** — at-cost pricing, no upsell, Cloudflare DNS is free and is what Phase 7 assumes. Best choice unless you have a strong reason otherwise.
> 2. **Porkbun** — low cost, clean UI, WHOIS privacy free.
> 3. **Namecheap** — fine, slightly pricier; WHOIS privacy free.
> 4. Avoid: GoDaddy (worst customer experience for a portfolio project).
>
> **Author action checklist:**
>
> - [ ] `mise.place` registered (TLD: `.place`)
> - [ ] WHOIS privacy / domain privacy enabled
> - [ ] Auto-renew enabled (Pitfall: a lapsed demo domain kills the portfolio)
> - [ ] DNS provider decided (Cloudflare recommended — Phase 7 DNS records go there)
> - [ ] "Coming soon" placeholder page pointed at the domain (Twilio 10DLC Brand step requires a live URL — see twilio-10dlc-setup.md Prerequisites)
> - [ ] Fields below filled
> - [ ] STATUS banner updated to `active`

---

- **Domain:** mise.place
- **Registrar:** TODO — fill in (Cloudflare / Porkbun / Namecheap / …)
- **Registered date:** TODO — YYYY-MM-DD
- **Expiry date:** TODO — YYYY-MM-DD (aim for 2+ years to reduce portfolio-expiry risk)
- **DNS provider:** TODO — Cloudflare DNS recommended for Phase 7
- **Auto-renew:** TODO — yes/no (should be yes)
- **WHOIS privacy:** TODO — yes/no (should be yes)
- **Placeholder page URL:** TODO — once DNS resolves and a "Coming soon" page is live, record the URL (required by Twilio runbook Prerequisites)

## Receipt / screenshot

- TODO: archive registrar receipt in a personal email folder tagged `mise/admin`

## Covers

- D-22 — Domain registered as a Day-1 admin precondition
- FOUND-05 (supporting evidence — Twilio Brand registration requires a live website URL)
