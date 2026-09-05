---
phase: 07-deploy-observability-portfolio-polish
plan: 02
type: execute
wave: 2
depends_on: ["07-01"]
autonomous: true
requirements: [DEPLOY-01]
files_modified:
  - ops/docker/web.Dockerfile
  - ops/docker-compose.yml
  - web/src/app/healthz/route.ts
  - web/next.config.ts
  - Makefile
  - CONTRIBUTING.md
  - tests/unit/test_compose_profiles.py
  - tests/unit/test_compose_images_are_pinned.py
  - tests/unit/test_dockerfiles_hardened.py

estimate:
  tokens: 68000
  raw_tokens: 68000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "D-119a: `docker build -f ops/docker/web.Dockerfile web/` produces an image that serves `GET /healthz` with body `ok` and binds `0.0.0.0` (the Next standalone `server.js` binds localhost unless `HOSTNAME=0.0.0.0`, which makes it unreachable from the compose network)."
    - "D-119: `docker compose -f ops/docker-compose.yml --profile prod config --services` lists exactly `kafka, redis, postgres, kafka-ui, migrate, topics, poller, state_machine, notifier, api, web`."
    - "D-121a: `docker compose -f ops/docker-compose.yml --profile smoke config --services` lists the same set minus `poller` — the 4.59 GB Playwright image stays off the CI smoke critical path while `make up-prod` remains the single human-facing command."
    - "D-119: every profiled service declares both `image:` (an explicit `ghcr.io/${GHCR_OWNER:-local}/mise-<svc>:${MISE_TAG:-dev}` tag) and `build:`, so `tests/unit/test_compose_images_are_pinned.py` stays green and a CD-built image can be pulled without a rebuild."
    - "D-119: `migrate` and `topics` run as one-shot services and every long-running service declares `depends_on: {migrate: {condition: service_completed_successfully}, topics: {condition: service_completed_successfully}}` — no service starts against an unmigrated database or a missing topic."
    - "D-119a: the broker is `apache/kafka:3.8.1` in every profile, configured with the `KAFKA_*` env prefix plus `CLUSTER_ID`, data at `/var/lib/kafka/data`, and a healthcheck invoking `/opt/kafka/bin/kafka-topics.sh` by absolute path because the scripts are not on `PATH`."
    - "D-119a: `make smoke` and any documented broker CLI invocation use the absolute `/opt/kafka/bin/` path, and `CONTRIBUTING.md` states that switching to this image requires `docker compose -f ops/docker-compose.yml down -v` once (the two log-dir layouts are not interchangeable)."
    - "DEPLOY-01 probe (concurrency — *if interrupted or run in parallel, what is guaranteed?*): `docker compose up -d --wait` is idempotent and convergent — a second invocation while the first is mid-start reconciles to the same desired state rather than duplicating containers (fixed `container_name` and compose's project lock), and an interrupted run leaves containers whose `depends_on: service_completed_successfully` ordering still holds on the next `up`. The `migrate` one-shot is safe to re-run because `alembic upgrade head` is idempotent; `topics` is safe because `scripts/create_topics.py` is idempotent."
  artifacts:
    - ops/docker/web.Dockerfile
    - web/src/app/healthz/route.ts
    - tests/unit/test_compose_profiles.py
  key_links:
    - "compose service names (`poller`, `state_machine`, `notifier`, `api`) → Prometheus scrape targets in 07-04. Prometheus resolves targets by compose service name; renaming a service here silently breaks a scrape job there."
    - "`web` service `NEXT_PUBLIC_*` **build args** → the browser bundle. Phase 6 D-110 inlines these at build time; setting them as runtime `environment:` does nothing at all."
    - "`kafka` healthcheck → every `depends_on: service_healthy` in the file. A healthcheck that cannot run (wrong script path on the new image) makes the whole `prod` profile hang at startup rather than fail."
  prohibitions:
    - "Must never commit a real `.env`; compose reads secrets through `env_file: [../.env]`, and `.env` is gitignored and dockerignored."
    - "Must never expose a service's debug or admin port on `0.0.0.0` in the compose file when loopback suffices."
    - "Must never run two different Kafka images across dev and prod profiles — that reintroduces exactly the dev/prod skew this phase exists to remove (07-RESEARCH Pitfall 5)."
  flagged_assumptions:
    - "Phase 6 (D-109) is assumed to have set `output: 'standalone'` in `web/next.config.*`. If it has not, Task 1 adds it — that is a build-configuration change to a Phase-6 file and must be called out in the SUMMARY rather than made silently."
    - "The `web` service's `NEXT_PUBLIC_API_BASE_URL` build arg is `http://localhost:8000` in compose, which is correct for a browser on the host but not for server-side fetches inside the network. Phase 6 D-110a makes every page render an offline state rather than crash, so this is safe for the smoke path; the production value is pending-human (Vercel env vars)."
---

<objective>
Turn the four service images plus the Next.js frontend into one runnable stack: a compose `prod` profile (everything), a `smoke` profile (everything except the Playwright poller), and the migration of the broker off the vendor-abandoned Bitnami legacy image.

Purpose: DEPLOY-01's honest deliverable under D-119 is "the whole system runs from this repository as a production-shaped stack." That claim is only true if one command brings up migrations, topics, four services and the web app in dependency order, and it is only credible in a portfolio if the broker image is one the vendor still maintains.

Output: `ops/docker/web.Dockerfile`, a `/healthz` route for `web/`, the `prod`/`smoke` profiles, the `apache/kafka:3.8.1` migration, `make up-prod`, and a compose-shape unit gate.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-CONTEXT.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-RESEARCH.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-PATTERNS.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-01-SUMMARY.md
@ops/docker-compose.yml
</context>

<artifacts_this_phase_produces>
- **Images:** `mise-web` (Next.js standalone on `node:22-alpine`) — completes the five-image set started in 07-01.
- **Compose services/profiles:** `prod` (all five services + `migrate` + `topics`), `smoke` (`prod` minus `poller`, D-121a); the `monitoring` profile is added to the same file in 07-04.
- **Scripts/targets:** `make up-prod`, and the corrected `make smoke` broker CLI path.
- **Docs:** the `CONTRIBUTING.md` Kafka volume-reset note.
- Metrics: this plan wires the `METRICS_PORT` env per service; the servers themselves land in 07-03.
</artifacts_this_phase_produces>

<tasks>

<task type="tracer">
  <name>Task 1 (tracer): the web image serves a health endpoint from the compose network</name>
  <files>ops/docker/web.Dockerfile, web/src/app/healthz/route.ts, web/next.config.ts, ops/docker-compose.yml, tests/unit/test_dockerfiles_hardened.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 3 (lines 399-440) — the verified `output: 'standalone'` image (340 MB, ready in 31 ms) and the three mandatory `COPY` steps, plus why `HOSTNAME=0.0.0.0` is load-bearing
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` D-109 and D-110 — the `web/` stack and the build-time `NEXT_PUBLIC_*` contract
    - `web/next.config.*` and `web/package.json` as they exist on disk
    - `ops/docker-compose.yml:38-52` — the service-block key order this file uses (`image, container_name, ports, environment, volumes, healthcheck, networks`)
  </read_first>
  <action>
Add `web/src/app/healthz/route.ts`: a route handler returning the plain-text body `ok` with
`export const dynamic = "force-dynamic"`, so the container healthcheck has a cheap non-prerendered
target and `up --wait` has a readiness signal. Phase 6 does not define one; this is a new file Phase 7
adds to `web/`, and the file's header comment says so.

Confirm `web/next.config.*` sets `output: "standalone"`. If Phase 6 did not set it, add it and note the
change in the SUMMARY — the standalone build is what makes a 340 MB image possible instead of ~1 GB.

Write `ops/docker/web.Dockerfile` as three stages on `node:22-alpine` per §Pattern 3: a `deps` stage
running `npm ci` with an npm cache mount; a `builder` stage that copies `node_modules` and the source,
declares `ARG NEXT_PUBLIC_API_BASE_URL` and `ARG NEXT_PUBLIC_SITE_URL` (promoted to `ENV` before the
build because these values are inlined into the bundle at build time and setting them at runtime does
nothing), and runs `npm run build`; and a runtime stage with `NODE_ENV=production`, `PORT=3000`,
`HOSTNAME=0.0.0.0`, a non-root `nextjs` user at uid 1001, the three copies (`public`,
`.next/standalone` into the workdir root, `.next/static`), a `HEALTHCHECK` using `wget --spider` against
`/healthz` (this base has wget and no curl), and `CMD ["node", "server.js"]`.

Add the `web` service to `ops/docker-compose.yml` with `profiles: [prod, smoke]`, `build.context: ../web`,
`build.dockerfile: ../ops/docker/web.Dockerfile`, the two `NEXT_PUBLIC_*` values passed as `build.args`
(not `environment`), `image: ghcr.io/${GHCR_OWNER:-local}/mise-web:${MISE_TAG:-dev}`, port
`3000:3000`, and `depends_on: {api: {condition: service_started}}`.

Update `tests/unit/test_dockerfiles_hardened.py`'s non-vacuity expectation to include `web`.
  </action>
  <acceptance_criteria>
    - `docker build -f ops/docker/web.Dockerfile -t mise-web:tracer web/` exits 0.
    - `docker run -d --rm -p 3010:3000 --name mise-web-tracer mise-web:tracer` then `curl -fsS http://127.0.0.1:3010/healthz` prints `ok`, and `curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:3010/` prints `200`.
    - `docker run --rm --entrypoint sh mise-web:tracer -c 'id -u'` prints `1001`.
    - `docker compose -f ops/docker-compose.yml --profile prod config --services | grep -x web` exits 0.
    - `docker compose -f ops/docker-compose.yml --profile prod config | grep -A2 'NEXT_PUBLIC_API_BASE_URL'` shows the value under `args`, and `grep -v '^#' ops/docker-compose.yml | grep -c 'NEXT_PUBLIC_API_BASE_URL: '` under the `web` service `environment:` key returns 0.
  </acceptance_criteria>
  <verify>
    <automated>docker build -f ops/docker/web.Dockerfile -t mise-web:tracer web/ && docker run -d --rm -p 3010:3000 --name mise-web-tracer mise-web:tracer && sleep 5 && test "$(curl -fsS http://127.0.0.1:3010/healthz)" = "ok"; rc=$?; docker rm -f mise-web-tracer >/dev/null 2>&1; exit $rc</automated>
  </verify>
  <done>The frontend goes from `web/` source through a standalone production build to a running, non-root container that answers a health probe on the compose network — the last of the five packaging paths is proven.</done>
</task>

<task type="auto">
  <name>Task 2: the `prod` and `smoke` compose profiles</name>
  <files>ops/docker-compose.yml, Makefile, tests/unit/test_compose_profiles.py, tests/unit/test_compose_images_are_pinned.py</files>
  <read_first>
    - `07-RESEARCH.md` §Code Examples "The `prod` profile service block" (lines 1047-1075) — the verified block shape, and why `image:` and `build:` appear together
    - `07-RESEARCH.md` §Pattern 5 (lines 593-606) — measured profile semantics: profile-less services always start; `service_completed_successfully` works for one-shots; `up --wait` exits 1 on an unhealthy waited-for container
    - `07-RESEARCH.md` §Open Questions 1 — why the poller is excluded from the smoke path (D-121a)
    - `tests/unit/test_compose_images_are_pinned.py:1-26` — the existing regex gate this file must keep satisfying
    - `Makefile:5-12` — the existing `up`/`down` targets
  </read_first>
  <action>
Add to `ops/docker-compose.yml` two one-shot services and four Python service blocks.

One-shots, both `profiles: [prod, smoke]`, `restart: "no"`, built from the state_machine image:
`migrate` runs `alembic upgrade head`; `topics` runs `python scripts/create_topics.py`. `migrate`
depends on `postgres: service_healthy`; `topics` depends on `kafka: service_healthy`.

Service blocks for `poller` (`profiles: [prod]` only), `state_machine`, `notifier`, `api` (all three
`profiles: [prod, smoke]`), each following the verified shape: `image:` with the
`ghcr.io/${GHCR_OWNER:-local}/mise-<svc>:${MISE_TAG:-dev}` tag, `build.context: ..` and the matching
`ops/docker/<svc>.Dockerfile`, `env_file: [../.env]`, an `environment:` map setting
`KAFKA_BOOTSTRAP_SERVERS: kafka:9092`, `REDIS_URL: redis://redis:6379/0`, both `DATABASE_URL_*` values
against the `postgres` service, `METRICS_PORT` (9101/9102/9103; the API serves `/api/metrics` on 8000
instead), and `ENV: prod`; `depends_on` on `kafka`/`redis`/`postgres` `service_healthy` plus both
one-shots `service_completed_successfully`; and `restart: unless-stopped`. The poller additionally sets
`shm_size: 512mb` — the default 64 MB `/dev/shm` crashes Chromium — and the `api` publishes `8000:8000`.

`poller` is the only service outside the `smoke` profile. Put a comment above its `profiles:` line
naming the reason: the smoke path injects raw polls with `scripts/replay_raw.py` and never scrapes
anything, so building and starting a 4.59 GB image would cost the CI job minutes to prove nothing.

Add `make up-prod` (`docker compose -f ops/docker-compose.yml --profile prod up -d --build --wait`) with
its `.PHONY` entry and `## description`.

Create `tests/unit/test_compose_profiles.py`: load the compose file with `yaml.safe_load` and assert the
profile-less service set is exactly `{kafka, redis, postgres, kafka-ui}`; that the `prod` profile
resolves to the eleven expected services and `smoke` to the same set minus `poller`; that every profiled
service declares `env_file`, an `image:` with a non-`latest` tag, and a `build:`; that `poller` declares
`shm_size`; that `state_machine`/`notifier` declare the `METRICS_PORT` values 9102/9103 and `poller`
9101; and that every long-running profiled service waits on both one-shots. Add the non-vacuity test:
at least 11 services parsed and the four expected service names present.

Extend `tests/unit/test_compose_images_are_pinned.py` with a second scan over `ops/docker/*.Dockerfile`
asserting every `FROM` line carries an explicit tag and none ends in `:latest` (the existing regex only
sees compose `image:` lines and is blind to `FROM`), with its own non-vacuity assertion.
  </action>
  <acceptance_criteria>
    - `docker compose -f ops/docker-compose.yml --profile prod config -q` exits 0.
    - `docker compose -f ops/docker-compose.yml --profile prod config --services | sort | tr '\n' ' '` equals `api kafka kafka-ui migrate notifier poller postgres redis state_machine topics web ` (order-insensitive set equality).
    - `docker compose -f ops/docker-compose.yml --profile smoke config --services | grep -cx poller` returns 0.
    - `docker compose -f ops/docker-compose.yml config --services | sort | tr '\n' ' '` equals `kafka kafka-ui postgres redis ` (profile-less services always start).
    - `uv run pytest tests/unit/test_compose_profiles.py tests/unit/test_compose_images_are_pinned.py -q` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>docker compose -f ops/docker-compose.yml --profile prod --profile smoke config -q && uv run pytest tests/unit/test_compose_profiles.py tests/unit/test_compose_images_are_pinned.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>One command brings the whole system up in dependency order, and a unit gate pins the profile membership, the port map, and the one-shot ordering so a later edit cannot quietly drop a service out of the stack.</done>
</task>

<task type="auto">
  <name>Task 3: migrate the broker to `apache/kafka:3.8.1`</name>
  <files>ops/docker-compose.yml, Makefile, CONTRIBUTING.md</files>
  <read_first>
    - `07-RESEARCH.md` §Pitfall 5 (lines 1003-1020) — the four-part change and its measured blast radius
    - `07-RESEARCH.md` §Code Examples "The `apache/kafka:3.8.1` env block" (lines 1077-1108) — verified booting to healthy
    - `ops/docker-compose.yml:4-36` — the block being replaced, including the comment that already anticipates this change (D-56)
    - `Makefile:50-52` — the `smoke` recipe's `kafka-console-consumer.sh` invocation
    - `tests/conftest.py:20-26` — testcontainers uses `confluentinc/cp-kafka:7.6.0` and is **unaffected**; do not touch it
  </read_first>
  <action>
Replace the `kafka` service block's image, environment, volume mount and healthcheck in one edit:
`image: apache/kafka:3.8.1`; the env prefix drops `CFG` (`KAFKA_NODE_ID`, `KAFKA_PROCESS_ROLES`,
`KAFKA_CONTROLLER_QUORUM_VOTERS`, `KAFKA_LISTENERS`, `KAFKA_ADVERTISED_LISTENERS`,
`KAFKA_LISTENER_SECURITY_PROTOCOL_MAP`, `KAFKA_CONTROLLER_LISTENER_NAMES`,
`KAFKA_INTER_BROKER_LISTENER_NAME`, the four replication/ISR settings, and
`KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"` which the D-27 startup guards depend on), and
`KAFKA_KRAFT_CLUSTER_ID` becomes `CLUSTER_ID` (the image's `configure` script refuses to start without
it). Add `KAFKA_LOG_DIRS: /var/lib/kafka/data` and move the volume mount to that path. The healthcheck
runs `/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list` by absolute path with
`start_period: 20s` — the broker scripts are not on `PATH` in this image, so the current healthcheck
command would fail forever and every `depends_on: service_healthy` would hang.

Replace the existing comment above the image line with one that records both facts: why the image moved
(the Bitnami legacy catalogue is vendor-declared no longer updated, last push 2025-07-18) and that this
is the swap D-56 anticipated.

Update the `Makefile` `smoke` recipe to invoke `/opt/kafka/bin/kafka-console-consumer.sh` by absolute
path. Leave the recipe's `up -d` + fixed sleep alone for now — 07-07 replaces the whole recipe with
`up -d --wait` plus the e2e suite.

Add a short section to `CONTRIBUTING.md` titled "Kafka image migration (one-time)" stating that the KRaft
metadata log layouts of the two images are not interchangeable, that `docker compose -f
ops/docker-compose.yml down -v` (or `docker volume rm mise_kafka-data`) is required once when switching,
and that dev topics and offsets are throwaway so nothing of value is lost. Name the follow-up commands:
`make up topics migrate seed`.
  </action>
  <acceptance_criteria>
    - `docker compose -f ops/docker-compose.yml down -v` then `docker compose -f ops/docker-compose.yml up -d kafka --wait --wait-timeout 120` exits 0.
    - `docker compose -f ops/docker-compose.yml exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list` exits 0.
    - `make topics && make migrate && make seed` all exit 0 against the fresh volume.
    - `grep -v '^#' ops/docker-compose.yml | grep -c 'KAFKA_CFG_'` returns 0, and the same filtered grep returns 1 for `CLUSTER_ID:`.
    - `grep -v '^#' Makefile | grep -c '/opt/kafka/bin/kafka-console-consumer.sh'` returns 1.
    - `uv run pytest tests/unit/test_compose_images_are_pinned.py tests/unit/test_compose_profiles.py -q` exits 0 and `uv run pytest tests/integration/test_topics_created.py -q` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>docker compose -f ops/docker-compose.yml up -d kafka --wait --wait-timeout 120 && docker compose -f ops/docker-compose.yml exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list && uv run pytest tests/unit/test_compose_profiles.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>Dev and prod run the same actively-maintained broker image, the healthcheck actually executes, and the one-time volume reset is documented where a contributor will hit it.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| host `.env` → container process | `env_file` injects every runtime secret; the file must never be committed or copied into a layer. |
| published container port → host network | `api:8000`, `web:3000`, `kafka:9094` are reachable from the host. |
| browser → `web` container | The Next server renders user-supplied route params. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-05 | Information disclosure | compose `env_file` | high | mitigate | `.env` stays gitignored and dockerignored (07-01); compose injects it at runtime only; the smoke job in 07-07 copies `.env.example`, never a real `.env`. |
| T-07-06 | Denial of service | poller `/dev/shm` | medium | mitigate | `shm_size: 512mb` on the poller service; the 64 MB default crashes Chromium mid-poll. |
| T-07-07 | Tampering | broker image supply | high | mitigate | Move off the vendor-abandoned `bitnamilegacy` image to the official ASF `apache/kafka:3.8.1`; every compose image carries an explicit tag, gated by `test_compose_images_are_pinned.py`. |
| T-07-08 | Spoofing | Kafka auto-topic creation | medium | accept | `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"` is preserved so a typo cannot silently mint a topic; broker auth is out of scope for a single-broker MVP on a private compose network, and this is stated in the README tradeoff section (07-08). |
| T-07-SC | Tampering | image builds | high | mitigate | `npm ci` against the committed `web/package-lock.json` and `uv sync --frozen` against `uv.lock`; no new package is introduced by this plan. Record in SUMMARY. |
</threat_model>

<verification>
1. `docker compose -f ops/docker-compose.yml --profile prod --profile smoke config -q` — exit 0.
2. `uv run pytest tests/unit -q -W error::RuntimeWarning` — exit 0, including the two compose gates and the extended Dockerfile gate.
3. `docker compose -f ops/docker-compose.yml down -v && make up topics migrate seed` — exit 0 on a fresh Kafka volume.
4. `uv run pytest tests/integration -q -p no:cacheprovider` — exit 0 (the testcontainers Kafka fixture is unaffected by the compose image swap).
5. `make images` still exits 0 and now includes `mise-web`.
</verification>

<success_criteria>
- `docker compose --profile prod up -d --wait` is a meaningful command: it builds and starts migrations, topics, four services and the web app in dependency order.
- The smoke profile excludes the poller and nothing else.
- The broker image is one the vendor still maintains, and the migration cost is documented where a contributor will hit it.
- Profile membership, the metrics port map, and image pinning are all pinned by unit tests.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-02-SUMMARY.md` when done.
Record: whether `output: "standalone"` had to be added to `web/next.config.*`, the `mise-web` image size,
the measured `up -d --wait` wall time for the `smoke` profile, and the exact `down -v` command a
contributor must run once.
</output>
