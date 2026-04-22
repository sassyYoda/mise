# GCP Project

> **STATUS: pending-admin-action**
>
> This file is an evidence template. The human operator must create the GCP
> project and enable the required APIs. Commands are listed below for copy-paste.
>
> **Why this is a template, not live evidence:** Creating a GCP project requires
> a Google account, a linked billing account with a credit card, and (if no
> existing organization) accepting Google Cloud ToS. None of these are
> performable from a coding agent context.
>
> **Author action checklist:**
>
> - [ ] `gcloud` CLI installed on the dev machine (`brew install --cask google-cloud-sdk`)
> - [ ] `gcloud auth login` completed with the Google account that will own the project
> - [ ] Billing account created (or reused) and its billing ID noted below
> - [ ] Project `mise-en-place-prod` created
> - [ ] Billing account linked to the project
> - [ ] `artifactregistry.googleapis.com` API enabled on project
> - [ ] `secretmanager.googleapis.com` API enabled on project
> - [ ] The five pre-generated secrets from 01-03-T3 mirrored into GCP Secret Manager: `HMAC_MGMT_SECRET_V1`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `RESY_ACCOUNTS_JSON`, plus the Twilio credentials once 01-03-T1 clears
> - [ ] STATUS banner updated to `active`

---

- **Project ID:** mise-en-place-prod
- **Project name:** Mise en Place
- **APIs enabled:**
  - artifactregistry.googleapis.com
  - secretmanager.googleapis.com
- **Created:** TODO — YYYY-MM-DD
- **Billing account linked:** TODO — yes/no (billing account ID: `XXXXXX-XXXXXX-XXXXXX` TODO)
- **Note:** Terraform IaC deferred to Phase 7. No resources except project + APIs at P1.

## Commands run

Copy/paste, expect status `ENABLED` for both services:

```bash
gcloud projects create mise-en-place-prod --name="Mise en Place" --set-as-default
gcloud services enable artifactregistry.googleapis.com --project=mise-en-place-prod
gcloud services enable secretmanager.googleapis.com --project=mise-en-place-prod
gcloud services list --project=mise-en-place-prod \
  --filter="config.name:(artifactregistry OR secretmanager)" \
  --format="table(config.name,state)"
```

Expected `gcloud services list` output (record verbatim once run):

```
NAME                              STATE
artifactregistry.googleapis.com   ENABLED
secretmanager.googleapis.com      ENABLED
```

TODO: paste real output here once executed.

## Secret mirroring (after 01-03-T3)

Once the project exists, mirror the four local-generated secrets from `.env`:

```bash
gcloud secrets create HMAC_MGMT_SECRET_V1 --project=mise-en-place-prod \
  --replication-policy=automatic \
  --data-file=- <<< "$(grep '^HMAC_MGMT_SECRET_V1=' .env | cut -d= -f2-)"

gcloud secrets create VAPID_PUBLIC_KEY --project=mise-en-place-prod \
  --replication-policy=automatic \
  --data-file=- <<< "$(grep '^VAPID_PUBLIC_KEY=' .env | cut -d= -f2-)"

gcloud secrets create VAPID_PRIVATE_KEY --project=mise-en-place-prod \
  --replication-policy=automatic \
  --data-file=- <<< "$(grep '^VAPID_PRIVATE_KEY=' .env | cut -d= -f2-)"

gcloud secrets create RESY_ACCOUNTS_JSON --project=mise-en-place-prod \
  --replication-policy=automatic \
  --data-file=- <<< "$(grep '^RESY_ACCOUNTS_JSON=' .env | cut -d= -f2-)"
```

Once Twilio 10DLC clears (01-03-T1), also mirror: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_MESSAGING_SERVICE_SID`, `TWILIO_FROM_NUMBER`, `TWILIO_TOLLFREE_FROM_NUMBER`.

## Covers

- D-23 — GCP project + Artifact Registry + Secret Manager enabled on Day 1
- FOUND-03 supporting — secrets have a production home before any code that reads them ships
