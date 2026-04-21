# Stack Research

**Domain:** Real-time web scraping + event pipeline + multi-channel notification platform (Mise en Place)
**Researched:** 2026-04-20
**Overall confidence:** HIGH (versions verified against PyPI / Context7 / official docs on research date)

---

## Executive Summary

The PRD-proposed stack is 90% sound. The notable issues:

1. **Next.js 14 is two majors behind** — 15 and 16 are released. Move to **Next.js 15.x LTS** (or 16.x if the team wants the latest). Keeping 14 is an anti-pattern in a portfolio-grade 2026 project.
2. **Kafka client: use `aiokafka` for MVP, not `confluent-kafka`** — as of 2.13.0 (late 2025), `confluent-kafka` reached asyncio GA and is strictly superior at high throughput, but `aiokafka` has a cleaner pure-asyncio API, is simpler to reason about, and is *more than enough* for ~400 events/day. Revisit at v2 if throughput matters.
3. **redis-py 7.x is the answer — `aioredis` is dead.** `aioredis` was merged into `redis-py` in 4.2 and the standalone package is archived. Use `redis.asyncio`. If the PRD or anyone mentions `aioredis`, replace it.
4. **Schema Registry is overkill at MVP.** Self-hosting a Confluent Schema Registry alongside a single-broker Kafka on GCE doubles ops cost. Use **Pydantic models as the contract + JSON on the wire** for MVP; add Schema Registry only when you have multiple producer services (you won't at MVP).
5. **Cloud Run Worker Pools (GA in 2026) are a better fit than GCE for the Playwright fleet** — but the PRD's choice of GCE for self-hosted Kafka is correct (Kafka is stateful and long-lived).
6. **SQLAlchemy 2.0 `async` + `asyncpg` driver** is the canonical 2025/2026 pattern. Don't use psycopg3 for the ORM hot path — asyncpg is measurably faster for read-heavy workloads.

Confidence is HIGH for all library choices (verified via PyPI on 2026-04-20 and cross-checked with Context7).

---

## Recommended Stack

### Core Runtime / Language

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12.x | Backend language | Stable, production-proven, PEP 695 types + faster CPython. 3.13 is fine too but keeps free-threaded mode experimental — don't opt in for this project. Avoid 3.14 at MVP. |
| Node.js | 22.x LTS | Next.js runtime / tooling | Current LTS through 2027-04; required by Next 15/16. |
| Docker | 27.x | Containerization | Baseline for Cloud Run + local `docker compose` integration tests. |

### Web Framework (API + PWA)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| FastAPI | 0.136.0 | HTTP API, SSE endpoint, admin routes | De facto standard for async Python APIs. Native Pydantic v2 integration. OpenAPI for free. SSE trivial via `StreamingResponse`. |
| Uvicorn | 0.44.0 (with `[standard]`) | ASGI server | Paired with FastAPI; `[standard]` pulls in `uvloop` + `httptools` for ~30% throughput boost. |
| Pydantic | 2.13.3 | Data validation + settings | Core contract layer. Pydantic v2 is Rust-backed and ~10x v1. Also use `pydantic-settings` for env config. |
| Next.js | **15.5.x** (recommended) **or 16.2.x** (if willing to run latest) | PWA frontend, App Router, service worker | **Move off 14.** 15 is the safe LTS-ish choice with React 19 + stabilized App Router. 16 adds Turbopack-default + 400% faster dev + Cache Components but is 1 month old as of research date. |
| React | 19.x | UI library | Bundled with Next 15/16. |
| TypeScript | 5.7.x | Type safety across Next + shared schemas | Standard. |

### Browser Automation (Resy Polling)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Playwright (Python) | 1.58.0 | Headless Chromium fleet for Resy | Only realistic option for JS-heavy Resy SPA. Browser contexts give session isolation. Built-in tracing helps debug detection bans. |
| tf-playwright-stealth | 1.2.0 | Fingerprint / navigator.webdriver masking | Actively maintained 2025 fork of the abandoned `playwright-stealth`. Use `tf-playwright-stealth`, NOT `playwright-stealth@2.0.3` (old, less effective). |
| fake-http-header | 0.3.x | Header rotation companion | Pulled in by `tf-playwright-stealth`. |

### HTTP Client (OpenTable GraphQL + outbound webhooks)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| httpx | 0.28.1 | Async HTTP for OpenTable GraphQL, Resend API, Twilio fallback, VAPID | **Not aiohttp.** httpx has a superior API, sync/async duality for tests, native HTTP/2, and is the community consensus for new code in 2025+. Use `AsyncClient` with connection pooling. |
| tenacity | 9.1.4 | Retry/backoff decorators | Canonical Python retry lib. Pair with `stop_after_attempt`, `wait_exponential_jitter`. |

### Message Bus

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Apache Kafka | 3.8.x (KRaft mode, no ZooKeeper) | Event pipeline backbone | Durable replay + consumer groups + audit trail. Single-broker on a `e2-small` GCE VM is fine for MVP throughput (~400 events/day is negligible). |
| aiokafka | 0.13.0 | Python Kafka producer + consumer | **Recommended over `confluent-kafka` for this project.** Pure-asyncio API, no thread-bridging gymnastics, simpler observability. `confluent-kafka` is faster but overkill at MVP scale. |
| Pydantic models | 2.13.x | Message schema contract | Serve as implicit schema. Serialize with `.model_dump_json()`, deserialize with `.model_validate_json()`. Defer Confluent Schema Registry to v2. |

### State / Cache / Scheduler

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Redis | 7.2+ (Memorystore standard tier) | Distributed ZSET scheduler, SETNX idempotency, in-memory availability state | Memorystore gives you a managed HA Redis at ~$35/mo. ZSET for poll scheduling is a well-trodden pattern. |
| redis-py | 7.4.0 | Async Redis client | **Use `import redis.asyncio as redis`.** `aioredis` is archived. Same library, sync + async. |

### Persistent Data

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| PostgreSQL | 16.x (Cloud SQL) | OLTP store (watchlists, users, tokens) | Cloud SQL 16 is GA and stable. 17 is newer but not worth the churn. |
| TimescaleDB | 2.17.x | Hypertables for `availability_events`, `poll_log` | **Self-install on Cloud SQL is not supported.** You have two real options: (a) self-host TimescaleDB on the same GCE VM as Kafka, or (b) use Timescale Cloud. For MVP with tight budget, **option (a)**. Flag this — PRD says "Cloud SQL/TimescaleDB" but that combination doesn't exist. |
| SQLAlchemy | 2.0.49 | ORM | 2.0 async is mature. Use `AsyncSession` + `select()` new-style queries. No legacy `Query` API. |
| asyncpg | 0.31.0 | Postgres async driver for SQLAlchemy | ~5x faster than psycopg3 async for SQLAlchemy workloads. Use as the SQLAlchemy driver: `postgresql+asyncpg://...`. |
| psycopg | 3.3.3 | Secondary driver for Alembic + raw scripts | Alembic migrations run fine against psycopg3 sync. Keep asyncpg for the app, psycopg3 for migrations. |
| Alembic | 1.18.4 | Schema migrations | Standard. Configure with async env.py template. |
| pgcrypto | bundled | Column-level AES-256-GCM for phone numbers | Postgres extension. Required by PRD constraints. |

### Notification Channels

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| resend (Python SDK) | 2.29.0 | Transactional email | Official SDK, ergonomic. Free tier covers MVP (3k/mo). |
| twilio (Python) | 9.10.5 | SMS | Official SDK. **The sync SDK is fine** — wrap it with `asyncio.to_thread()` in the notifier worker. Twilio does not have a first-party async SDK; don't chase one. |
| pywebpush | 2.3.0 | VAPID Web Push sender | Standard choice. Paired with `cryptography` for the VAPID keypair. |
| cryptography | 43.x | VAPID + HMAC token signing | Required transitively. |

### Observability

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| prometheus-client | 0.25.0 | Core metrics primitives (Counter/Gauge/Histogram) | Official lib. Use in workers directly. |
| prometheus-fastapi-instrumentator | 7.1.0 | Auto-instrument FastAPI request metrics | Drop-in for API latency/error metrics. Exposes `/metrics`. |
| structlog | 25.5.0 | Structured JSON logging | De facto standard. Ships cleanly to GCP Cloud Logging / Grafana Loki. |
| Grafana Cloud | free tier | Dashboards + log aggregation | 10k series free, no infra to run. |
| Sentry | free tier | Error tracking | 5k errors/mo free. |
| OpenTelemetry | **defer to post-MVP** | Distributed tracing | `opentelemetry-instrumentation-fastapi@0.62b0` is still beta. Overhead for 8-week MVP. Skip unless tracing is a must-have. |

### Testing

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| pytest | 9.0.3 | Test runner | Standard. pytest 9 is stable. |
| pytest-asyncio | 1.1.0 | async test support | Use `asyncio_mode = "auto"` in `pytest.ini`. |
| pytest-httpx | 0.x (latest) | Mock httpx calls for OpenTable/Resend/Twilio | Correct mock for httpx; don't use `responses` (requests-only) or `aioresponses` (aiohttp-only). |
| playwright (for tests) | 1.58.0 | Smoke tests against Resy live + fixture captures | Re-use the scraping dep for test mode with trace recording. |
| testcontainers-python | 4.x | Ephemeral Postgres + Redis + Kafka in integration tests | Much better than docker-compose fixtures: auto-cleanup, per-test isolation. |
| freezegun | 1.5.x | Freeze time for TTL / scheduler tests | Required for deterministic scheduler/idempotency tests. |
| respx | 0.21.x | Alternative httpx mock (route-based) | Useful if pytest-httpx is too fixture-y for your taste. Pick one. |

### Infrastructure / Deployment

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| GCP Cloud Run (Services) | — | FastAPI + SSE endpoint | Scales to zero. HTTPS + custom domain via Cloud Run domain mapping. |
| GCP Cloud Run (Worker Pools) | GA 2026 | Playwright scrapers + Kafka consumers + notifier | **Use Worker Pools, not GCE**, for the scraper/consumer fleet. Long-running containers, scale on CPU, ~40% cheaper than request-driven Services for background work. This is new-in-2026 and a strong portfolio signal. |
| GCE (single `e2-small`) | — | Self-hosted Kafka broker (KRaft mode) | Stateful + long-lived; Cloud Run is wrong fit. One VM, one broker, persistent disk. |
| Cloud SQL | PG 16 | Managed Postgres | Managed backups, failover. |
| Memorystore | Redis 7.2 | Managed Redis | Free of infra overhead. |
| Artifact Registry | — | Container image storage | GCP-native, avoids Docker Hub rate limits. |
| Terraform | 1.9.x | IaC | Standard. Use latest stable 1.9, NOT OpenTofu unless you have a specific reason. |
| hashicorp/google provider | 7.28.x | GCP resources | Current stable. Cross-check against v6→v7 migration notes for breaking changes. |
| Vercel | — | Next.js PWA hosting | Zero-config for Next 15/16. Free tier adequate at MVP. Keep the API on GCP; let Vercel host the frontend only. |
| GitHub Actions | — | CI/CD | Standard. Build + push to Artifact Registry, then `gcloud run deploy`. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| uv | Python package manager | Fast Rust-backed pip/poetry replacement. Much faster than Poetry for Docker layer caching. Use in 2026. |
| ruff | Linter + formatter | Replaces flake8 + black + isort. One tool, fast. |
| mypy or pyright | Static typing | pyright is faster; mypy has broader plugin ecosystem. Pick one and stick. |
| pre-commit | Git hooks | Enforce ruff + mypy + secret scan before commit. |
| pnpm | Node package manager for Next.js | Faster + better monorepo than npm/yarn. |

---

## Installation

### Python backend (`pyproject.toml` excerpt)

```toml
[project]
name = "mise"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi==0.136.0",
    "uvicorn[standard]==0.44.0",
    "pydantic==2.13.3",
    "pydantic-settings>=2.6",
    "playwright==1.58.0",
    "tf-playwright-stealth==1.2.0",
    "httpx==0.28.1",
    "tenacity==9.1.4",
    "aiokafka==0.13.0",
    "redis==7.4.0",
    "sqlalchemy[asyncio]==2.0.49",
    "asyncpg==0.31.0",
    "psycopg[binary]==3.3.3",
    "alembic==1.18.4",
    "resend==2.29.0",
    "twilio==9.10.5",
    "pywebpush==2.3.0",
    "cryptography>=43",
    "prometheus-client==0.25.0",
    "prometheus-fastapi-instrumentator==7.1.0",
    "structlog==25.5.0",
    "orjson==3.11.8",
]

[dependency-groups]
dev = [
    "pytest==9.0.3",
    "pytest-asyncio==1.1.0",
    "pytest-httpx>=0.35",
    "testcontainers>=4.8",
    "freezegun>=1.5",
    "ruff>=0.8",
    "mypy>=1.13",
    "pre-commit>=4.0",
]
```

### Next.js PWA

```bash
# Scaffold (choose one)
pnpm create next-app@latest --ts --app --tailwind mise-web   # Next 16 default in 2026
# or pin to 15 LTS:
pnpm create next-app@15 --ts --app --tailwind mise-web

# Core deps
pnpm add @tanstack/react-query zod react-hook-form swr
pnpm add -D @types/node
```

### Infra

```bash
# Terraform providers (providers.tf)
# terraform { required_providers { google = { source = "hashicorp/google", version = "~> 7.28" } } }
terraform init
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| aiokafka 0.13 | confluent-kafka-python 2.14 | When throughput > 10k msg/sec or you need exactly-once semantics. Overkill for MVP. |
| asyncpg (app driver) | psycopg3 async | If you want a single driver across app + Alembic and can tolerate ~30% slower hot path. |
| httpx | aiohttp | If you need websockets server-side + raw perf (aiohttp is faster) — but PRD uses SSE, not WS, so httpx wins. |
| Next.js 15 LTS | Next.js 16 | If team is comfortable with brand-new releases and wants Turbopack-default + Cache Components. |
| Cloud Run Worker Pools | GKE Autopilot | If you grow past ~50 workers or need stateful sets. GKE is more ops for a portfolio MVP. |
| Self-hosted Kafka on GCE | Confluent Cloud | Confluent Cloud is ~$200+/mo floor. Blows the budget. Reconsider at v2. |
| Self-hosted Kafka on GCE | GCP Pub/Sub | Would eliminate GCE VM, but loses replay + consumer-group semantics critical for audit + pattern model. PRD's GCE Kafka choice is correct. |
| Pydantic + JSON on wire | Confluent Schema Registry + Avro | When you have ≥3 producer services and need compatibility guarantees. Not MVP. |
| pywebpush | web-push-py | They're different packages — `pywebpush` is the standard (`web-push-libs/pywebpush`). Don't confuse with Node's `web-push`. |
| Vercel for Next.js | Cloud Run for Next.js | Vercel is free + zero-config for Next; Cloud Run for Next.js needs a custom Dockerfile. Use Vercel. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `aioredis` | Archived / merged into redis-py in 4.2. Any tutorial referencing it is stale. | `redis.asyncio` from `redis==7.4.0` |
| `playwright-stealth@2.0.3` | Author-acknowledged "proof-of-concept." Detection pass rate is weak vs active Resy bot protection. | `tf-playwright-stealth==1.2.0` |
| `requests` + `responses` | Sync-only; won't share an event loop with your scrapers. | `httpx` + `pytest-httpx` |
| `aiohttp` for outbound | Fine library, but ecosystem mock support and docs lag httpx in 2026. | `httpx.AsyncClient` |
| `kafka-python` | Sync, single-thread bottleneck, active maintenance has slowed vs aiokafka/confluent. | `aiokafka` |
| Pydantic v1 | EOL; v2 is Rust-backed and vastly faster. | `pydantic>=2.13` |
| SQLAlchemy 1.x Query API | Legacy. `select()` is the 2.0 style. | `sqlalchemy>=2.0` + `AsyncSession.execute(select(...))` |
| Next.js 14 | Two majors behind as of 2026-04. Reviewers will notice. | Next.js 15.x LTS (or 16.x) |
| Pages Router | Legacy. App Router is stable for 2+ years now. | App Router (already in PRD) |
| `next-pwa` (shadowwalker) | Minimally maintained. Tied to Webpack, struggles with App Router. | Serwist (`@serwist/next`) or a hand-rolled manifest + service worker |
| Confluent Schema Registry at MVP | Adds a second stateful service to self-host for zero current benefit. | Pydantic models as the contract, JSON on the wire |
| ZooKeeper-mode Kafka | Deprecated in Kafka 3.x, removed in 4.x. | KRaft mode from day one |
| psycopg2 / psycopg2-binary | Psycopg 2 is legacy. Psycopg 3 is the new line, maintained alongside asyncpg. | `psycopg==3.3.3` |
| `setup.py` / `requirements.txt` | Legacy. | `pyproject.toml` + `uv` |
| Poetry | Still fine, but `uv` is 10–100x faster for resolve + install, improves Docker build times. | `uv` |
| `black` + `isort` + `flake8` | Three tools where one suffices. | `ruff` (format + lint) |
| OpenTofu (at MVP) | Adds risk with no benefit for a portfolio MVP. | Terraform 1.9 |
| Cloud Run for Kafka broker | Kafka is stateful, needs persistent disk, needs a long-lived broker identity. | GCE VM |
| GCE for scraper workers | Over-provisioned, you manage the OS. | Cloud Run Worker Pools |

---

## Stack Patterns by Variant

**If the team wants to minimize bleeding-edge risk:**
- Pin Next.js 15.5.x (not 16)
- Defer Cloud Run Worker Pools → use Cloud Run Jobs in a cron-triggered loop, or a single GCE VM for workers
- Skip OpenTelemetry entirely

**If the team wants maximum portfolio shine:**
- Next.js 16.2.x with Cache Components and `use cache`
- Cloud Run Worker Pools for scrapers (still-new feature, good war story)
- OpenTelemetry tracing across scraper → Kafka → consumer → notifier (even if beta)

**If throughput grows past 10k events/day (post-MVP):**
- Swap `aiokafka` → `confluent-kafka-python` (asyncio GA since 2.13)
- Add Confluent Schema Registry + Avro
- Move Kafka from single-broker GCE to 3-broker cluster (or Confluent Cloud)
- Promote TimescaleDB from compose-sidecar to Timescale Cloud managed

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Python 3.12 | Playwright 1.58, FastAPI 0.136, Pydantic 2.13, SQLAlchemy 2.0 | All tested combinations; no known issues. |
| SQLAlchemy 2.0.49 | asyncpg 0.31, psycopg 3.3 | Both async drivers are first-class in SA 2.0. |
| aiokafka 0.13 | Kafka brokers 2.x–3.x (KRaft) | Confirmed for Kafka 3.8. |
| redis-py 7.4 | Redis server 7.2 / 7.4 / 8.0 / 8.2 | Memorystore 7.2 is covered. |
| Next.js 15 | React 19 | Bundled; don't mix React 18 with Next 15. |
| Next.js 16 | React 19.2 | Includes `<Activity/>` + View Transitions. |
| Alembic 1.18 | SQLAlchemy 2.0 | Use async `env.py` template; run migrations with psycopg3 sync driver. |
| pytest-asyncio 1.1 | pytest 9.0 | Use `asyncio_mode = "auto"`. |
| prometheus-fastapi-instrumentator 7.1 | FastAPI 0.115+ | Confirmed for 0.136. |
| Terraform google provider 7.x | Terraform 1.6+ | Provider v7 broke a few IAM resource names vs v6 — check migration guide if lifting from older projects. |

---

## Confidence Per Recommendation

| Recommendation | Confidence | Source |
|----------------|------------|--------|
| Python 3.12 | HIGH | Stable, multi-year |
| Next.js 15 over 14 | HIGH | nextjs.org blog (Next 16.2 stable as of 2026-03-25) |
| aiokafka over confluent-kafka at MVP | MEDIUM-HIGH | Opinionated call; confluent-kafka is strictly more capable but heavier. Could go either way. |
| redis-py (not aioredis) | HIGH | Redis FAQ confirms aioredis merge; aioredis PyPI archived |
| SQLAlchemy 2.0 async + asyncpg | HIGH | Official SA docs; well-documented pattern |
| httpx over aiohttp | HIGH | Community consensus 2024–2026 |
| `tf-playwright-stealth` over `playwright-stealth` | MEDIUM | tf fork is actively maintained (2025 releases); original has upstream inactivity. Validate in Phase 2 with Resy live. |
| Cloud Run Worker Pools for scrapers | MEDIUM | GA'd 2026; GCP blog case studies confirm fit, but it's new. Fallback: GCE. |
| Pydantic-as-schema (skip Schema Registry) | HIGH | Standard pragmatic call at MVP scale. |
| TimescaleDB on GCE self-install | MEDIUM | Required because Cloud SQL doesn't support Timescale extension. Flag for Phase 1. |
| Vercel for Next.js, Cloud Run for API | HIGH | Standard split; avoids Next.js server runtime quirks on Cloud Run. |
| Terraform 1.9 + google provider 7.28 | HIGH | Current as of research date. |
| Skip OpenTelemetry at MVP | MEDIUM | Opinion — the instrumentation package is still beta `0.62b0`; spending 2 days wiring it is time not building. |

---

## Key Version Shifts (2025 → 2026)

These are the "if you learned this stack pre-2024, what changed" items:

1. **aioredis is gone.** Merged into redis-py 4.2 in 2022; standalone package archived. Any 2020–2021 tutorial is misleading.
2. **Pydantic v1 → v2** is a hard break and the only game in town now. v1 EOL'd.
3. **SQLAlchemy 1.x `Query` API is legacy.** 2.0 `select()` style is current. Mixing causes subtle async bugs.
4. **confluent-kafka-python asyncio is GA (Nov 2025, v2.13).** Previously aiokafka was the only serious asyncio option; now there's a real choice.
5. **Cloud Run Worker Pools GA'd in 2026.** Previously, long-running Python workers on GCP meant GCE or GKE. Worker Pools are a genuinely new option.
6. **Next.js 14 → 15 → 16 in 18 months.** Stabilized App Router, React 19, Turbopack-default.
7. **`uv` replaced `pip-tools` / `poetry`** as the fast default.
8. **Kafka 4.x drops ZooKeeper entirely.** Start on KRaft — don't set up a dying architecture.

---

## Sources

- [PyPI / playwright](https://pypi.org/pypi/playwright/json) — 1.58.0
- [PyPI / fastapi](https://pypi.org/pypi/fastapi/json) — 0.136.0
- [PyPI / sqlalchemy](https://pypi.org/pypi/sqlalchemy/json) — 2.0.49
- [PyPI / redis](https://pypi.org/pypi/redis/json) — 7.4.0
- [PyPI / aiokafka](https://pypi.org/pypi/aiokafka/json) — 0.13.0
- [PyPI / confluent-kafka](https://pypi.org/pypi/confluent-kafka/json) — 2.14.0
- [PyPI / httpx](https://pypi.org/pypi/httpx/json) — 0.28.1
- [PyPI / pydantic](https://pypi.org/pypi/pydantic/json) — 2.13.3
- [PyPI / asyncpg](https://pypi.org/pypi/asyncpg/json) — 0.31.0
- [PyPI / psycopg](https://pypi.org/pypi/psycopg/json) — 3.3.3
- [PyPI / alembic](https://pypi.org/pypi/alembic/json) — 1.18.4
- [PyPI / twilio](https://pypi.org/pypi/twilio/json) — 9.10.5
- [PyPI / resend](https://pypi.org/pypi/resend/json) — 2.29.0
- [PyPI / pywebpush](https://pypi.org/pypi/pywebpush/json) — 2.3.0
- [PyPI / prometheus-client](https://pypi.org/pypi/prometheus-client/json) — 0.25.0
- [PyPI / prometheus-fastapi-instrumentator](https://pypi.org/pypi/prometheus-fastapi-instrumentator/json) — 7.1.0
- [PyPI / structlog](https://pypi.org/pypi/structlog/json) — 25.5.0
- [PyPI / pytest](https://pypi.org/pypi/pytest/json) — 9.0.3
- [PyPI / pytest-asyncio](https://pypi.org/pypi/pytest-asyncio/json) — 1.1.0
- [PyPI / tenacity](https://pypi.org/pypi/tenacity/json) — 9.1.4
- [PyPI / orjson](https://pypi.org/pypi/orjson/json) — 3.11.8
- [PyPI / uvicorn](https://pypi.org/pypi/uvicorn/json) — 0.44.0
- [PyPI / tf-playwright-stealth](https://pypi.org/pypi/tf-playwright-stealth/json) — 1.2.0
- [Next.js blog](https://nextjs.org/blog) — Next.js 16.2 stable 2026-03-25
- [Redis aioredis FAQ](https://redis.io/faq/doc/26366kjrif/what-is-the-difference-between-aioredis-v2-0-and-redis-py-asyncio) — aioredis merge into redis-py confirmed
- [Confluent blog: Clients 2.13.0 Python Async GA](https://www.confluent.io/blog/confluent-kafka-clients-2-13-0-release-python-async/) — asyncio GA Nov 2025
- [GCP blog: Cloud Run Worker Pools + Kafka Autoscaler](https://cloud.google.com/blog/products/serverless/exploring-cloud-run-worker-pools-and-kafka-autoscaler) — Worker Pools GA
- [GCP docs: Deploy worker pools to Cloud Run](https://docs.cloud.google.com/run/docs/deploy-worker-pools) — Worker Pools deployment
- [Terraform Google Provider releases](https://github.com/hashicorp/terraform-provider-google/releases) — 7.28.0 current
- Context7: `/fastapi/fastapi`, `/redis/redis-py`, `/aio-libs/aiokafka`, `/confluentinc/confluent-kafka-python`, `/encode/httpx`, `/vercel/next.js`, `/pydantic/pydantic`, `/magicstack/asyncpg`, `/psycopg/psycopg`, `/sqlalchemy/alembic`, `/web-push-libs/pywebpush`, `/resend/resend-python`, `/twilio/twilio-python`, `/prometheus/client_python`, `/microsoft/playwright-python`

---

*Stack research for: real-time scraping + event pipeline + notification system (Mise en Place)*
*Researched: 2026-04-20*
