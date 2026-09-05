---
phase: 05-api-watchlist-crud-sse
plan: 05
type: execute
wave: 5
depends_on: [05-04]
files_modified:
  - shared/kafka.py
  - shared/redis_keys.py
  - services/api/sse.py
  - services/api/routers/feed.py
  - services/api/routers/restaurants.py
  - services/api/routers/health.py
  - services/api/schemas.py
  - services/api/config.py
  - services/api/app.py
  - tests/unit/test_sse_framing.py
  - tests/unit/test_feed_hub.py
  - tests/unit/test_feed_consumer_config.py
  - tests/unit/test_api_async_only.py
  - tests/integration/test_sse_live.py
  - tests/integration/test_restaurants_api.py
autonomous: true
requirements: [API-02, API-03]

estimate:
  tokens: 76000
  raw_tokens: 76000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Exactly ONE background task per API process consumes `availability.events` through a groupless consumer — no group id, latest offset reset, auto-commit disabled — and multicasts to every connected client's own queue; a consumer per SSE connection is the named anti-pattern this design exists to avoid (D-98, ARCHITECTURE Anti-Pattern 4)."
    - "`commit()` is never called on the feed consumer and no group id is ever set: with no group there are no offsets, which is precisely what lets every API replica see every event. A unit test asserts the factory's three settings, and a comment states that adding a group id would silently make each event reach ONE replica's clients instead of all of them (D-98, D-98a, research Pitfall 6)."
    - "The feed consumer reuses the existing topic-existence guard before starting, because a groupless consumer whose topic is absent from metadata dies at start-up while the process keeps serving healthy liveness responses and an eternally silent stream (D-98a, research §Startup guard)."
    - "`GET /api/feed/live` returns a streaming response with the event-stream content type, no-cache, the proxy no-buffering header and keep-alive, writing an id line, an event-name line, a data line and a terminating blank line per event, and a comment line as a heartbeat every 15 seconds produced by a timed wait on the queue — never by a sleep loop, which would add up to a full heartbeat interval of latency to every event (D-98, research Pattern 4)."
    - "SC3: an event published to Kafka reaches a connected client's first byte within 500 ms, measured against a REAL in-process server rather than a buffering transport, which is structurally incapable of incremental streaming and hangs forever on an infinite generator (D-99, D-104a / BC-1). Research measured roughly 18 ms end to end — a 27x margin — so a failure here is a regression, not a tight budget."
    - "PROBE API-02/concurrency: `publish` is a synchronous function that never awaits. On a full queue it drops the OLDEST item for THAT connection only and increments the drop counter; the ring buffer and every other connection are unaffected. Being synchronous is also what makes iterating the subscriber set safe — with no suspension point inside the loop, no other coroutine can subscribe or unsubscribe mid-iteration (D-98, research Pattern 2)."
    - "Per-connection cleanup lives in the generator's `finally`: uvicorn closes the async generator when the client disconnects, so the queue is unsubscribed and the active-connection gauge decremented promptly; the disconnect-polling helper is not used, because it reports false throughout a live stream and deadlocks under the buffering transport (research Pattern 3)."
    - "`Last-Event-ID` is read from the header OR the query parameter, and replays the ring-buffer events AFTER that id before streaming live; an id that has rotated out of the ring replays the whole buffer, because a live activity feed prefers a few duplicates the browser can dedupe on event id over a silent gap — and that choice is stated in `docs/api.md` rather than left implicit (D-98, research §Last-Event-ID replay)."
    - "`GET /api/feed/recent` serves the ring buffer with the limit clamped to a maximum of 50, falling back to the most recent `availability_events` rows ordered by time descending when the buffer cannot answer — the table's primary key makes that the correct ordering, and the per-process ring is why a fresh replica must have a fallback at all (D-98, research Pitfall 3)."
    - "Each event is enriched with the restaurant name, slug and neighbourhood EXACTLY ONCE in the pump, behind a bounded cache keyed on the source and the STRINGIFIED platform id — the event's restaurant id is an integer while the restaurants column is text, and a cache with a 100 percent miss rate is the symptom of getting that wrong (D-98, research Pitfall 2)."
    - "A malformed message does not kill the pump: the per-message handler logs the failure shape and continues, and an unhandled pump death is surfaced by `/readyz`, which checks that the pump task exists and is not done and reports the scrubbed exception when it is (D-98, research Pitfall 7)."
    - "`GET /api/restaurants` filters by a name, neighbourhood or cuisine substring and by exact neighbourhood, cuisine and price tier, clamps its limit, and orders by a deterministic tiebreaker so no row can appear on two pages; membership tests against the party-size array use scalar-membership rather than the generic array container operator, which raises rather than working (D-100, research §ARRAY)."
    - "`GET /api/restaurants` and `GET /api/restaurants/{slug}` return the MERGED logical restaurant: one object per slug carrying a list of its source rows, the active watch count read from the `watch:count` HASH, its recent availability events across all its source rows, and its cover photo (D-100)."
    - "`GET /api/stats` returns the active watch count, the 24-hour event count, the 24-hour notification count and the restaurant count, cached in Redis for 30 seconds through a key registered in the shared key module (D-100)."
    - "The instrumentator's streaming-duration exclusion configured in 05-01 is verified against a real SSE connection: a connection held open for seconds contributes no observation of that length to the request-duration histogram (D-101a)."
  artifacts:
    - services/api/sse.py
    - services/api/routers/feed.py
    - services/api/routers/restaurants.py
    - tests/unit/test_sse_framing.py
    - tests/unit/test_feed_hub.py
    - tests/unit/test_feed_consumer_config.py
    - tests/integration/test_sse_live.py
    - tests/integration/test_restaurants_api.py
  key_links:
    - "Kafka `availability.events` -> the single pump -> N per-connection queues -> the browser's EventSource. The synchronous publish is the load-bearing detail: one awaited put would let the slowest connected browser stall the pump and every other client's feed behind it (research Pattern 2)."
    - "the ring buffer -> `Last-Event-ID` replay AND `/api/feed/recent`. The ring survives a dropped connection, which is what makes a reconnect able to fill its own gap; a drop caused by a slow client must therefore not touch the ring."
    - "the topic-existence guard -> the pump's start -> `/readyz`. Without the guard the app starts, liveness passes, and the feed is permanently silent — the worst failure shape for a portfolio demo (D-98a)."
    - "`watch:count` (written in 05-02 and 05-04) -> `GET /api/restaurants`' active watch count. The API is both writer and reader of that hash; the field key must be built with the same helper on both sides or the count reads as zero (D-95b)."
    - "the in-process server fixture from 05-01 -> every assertion in this plan's SSE module. It is the only tier that runs lifespan and streams incrementally (BC-1)."
  prohibitions:
    - "MUST NOT create a Kafka consumer per SSE connection, and MUST NOT set a group id on the feed consumer."
    - "MUST NOT call `commit()` on the feed consumer, and MUST NOT call `assign()` on it — doing so disables the automatic reassignment that a groupless consumer gets on a metadata change."
    - "MUST NOT make the publish path awaitable, and MUST NOT await anything inside the subscriber iteration."
    - "MUST NOT implement the heartbeat as a sleep loop; it is a timed wait on the queue read."
    - "MUST NOT broadcast user-scoped data on the feed — no watch id, user id, email, phone or notification row ever reaches this channel; the feed carries public availability only."
    - "MUST NOT use the request disconnect-polling helper for cleanup; the generator's `finally` is the mechanism."
    - "MUST NOT write an SSE assertion against a buffering transport; every streaming test uses the in-process server fixture."
    - "MUST NOT let one malformed message terminate the pump."
    - "MUST NOT use the generic array container operator on the party-size column; it raises for the base array type."
---

<objective>
Turn the Kafka event stream into a live browser feed and expose the public read surface the Phase 6
PWA is built on: one background consumer per process multicasting to per-connection queues, a
heartbeated SSE endpoint with ring-buffer replay, a recent-events hydration route with a database
fallback, merged restaurant search and detail, and a cached stats counter.

Purpose: SC3 — first event within 500 ms through a real server — is the one performance claim in this
phase, and BC-1 established that the locked test approach cannot measure it at all: the buffering
transport accumulates the whole response before returning and hangs forever on an infinite generator.
Everything in this plan is therefore written against a real in-process server, and the fan-out is
built so that a single slow browser can never stall the pump that serves everyone else.
Output: the hub and its pump, the groupless consumer factory, the feed and restaurant routers, the
stats cache key, and five test modules including the SC3 measurement.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md
@.planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md
@.planning/phases/05-api-watchlist-crud-sse/05-04-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — an event published to Kafka reaches a live SSE client's first byte inside the SC3 budget</name>
  <files>shared/kafka.py, services/api/sse.py, services/api/routers/feed.py, services/api/routers/health.py, services/api/config.py, services/api/app.py, tests/unit/test_feed_consumer_config.py, tests/integration/test_sse_live.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Kafka Consumer Without a Group (executed)" — the auto-assignment source read, the commit error, the cancellation and shutdown order, the start-up guard, and the latest-offset race note
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Server-Sent Events (executed)" — the wire format, the verified response headers, and the latency table
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Code Examples" — "FeedHub (the parts that matter)" and "Lifespan with `AsyncExitStack` and lifespan state"
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Architecture Patterns" Patterns 2, 3 and 4, and §"Common Pitfalls" Pitfalls 2, 6 and 7
    - .planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md §"`services/api/sse.py`" — the sibling-factory rule and why the existing consumer factory must not be widened
    - shared/kafka.py lines 40-85 (`make_consumer` and its docstring claims about being an async factory)
    - services/state_machine/main.py lines 60-135 (the topic-existence guard and the `AsyncExitStack` lifespan with its LIFO teardown)
    - shared/events.py (the `AvailabilityEvent` wire model this pump decodes, and the note that its restaurant id is the platform id as an integer)
    - tests/unit/test_kafka_consumer_config.py (the analog for the config-assertion test)
    - tests/integration/conftest.py (`live_api`, `api_app`, `create_topics`)
  </read_first>
  <behavior>
    - The feed consumer factory produces a consumer with no group id, auto-commit disabled and the latest offset reset; a unit test asserts all three.
    - Calling commit on that consumer raises, and the pump never calls it.
    - Starting the hub against a broker with the topic present succeeds; against a broker missing the topic it fails at start-up with a message naming the topic, rather than starting silently.
    - A client connected to the live feed receives a connected comment immediately.
    - An event published to Kafka after the hub reports itself assigned reaches the client's first data frame within 500 ms.
    - The received frame carries an id line equal to the event id, an event-name line, a single-line data payload, and a terminating blank line.
    - The response carries the event-stream content type, no-cache, the proxy no-buffering header, and a chunked transfer encoding proving it is not buffered.
    - With the heartbeat interval configured short, a client that receives no events gets a comment frame within roughly that interval.
    - Disconnecting the client returns the hub's connection count to zero within a second and decrements the active-connection gauge.
    - Readiness reports the feed unhealthy when the pump task has finished, and the scrubbed exception appears in the response.
  </behavior>
  <action>
Add a sibling factory to `shared/kafka.py` for the groupless feed consumer rather than widening the
existing one. The existing factory requires a group id and hard-wires the earliest offset reset;
widening its signature would let a worker service silently lose its offsets, which is a far worse
failure than one extra function. The new factory sets no group id, the latest offset reset and
auto-commit disabled, and keeps the module's existing claims in its docstring — that consumers are
created only through these factories and that being an async factory makes construction at import
time structurally impossible. Add a comment stating the pairing that looks like a contradiction and
will otherwise be "fixed": with no group there are no offsets, so disabling auto-commit is a
statement of intent, and adding a group id would make each event reach one replica's clients rather
than all of them.

Write `services/api/sse.py`. Take the executed hub sketch from research as the source; it is already
strict-clean. It holds the subscriber set, the bounded ring buffer keyed by event id, a synchronous
publish that drops the oldest item for a full queue and increments the drop counter, subscribe and
unsubscribe, and a replay-after helper. The publish function's docstring states, in full, why it is
synchronous: an awaited put would block the single pump on the slowest connected browser, and having
no suspension point inside the subscriber loop is also what makes that iteration safe against a
concurrent subscribe or unsubscribe. Add a comment saying this synchronous function performs no I/O,
so the repo's async-only rule is satisfied and a future gate should not "fix" it.

The pump is one task: start the consumer, then loop reading one message at a time, decoding it into
the shared event model, enriching it with the restaurant name, slug and neighbourhood through a
bounded cache keyed on the source and the STRINGIFIED platform id — the event carries an integer and
the restaurants column is text, and the symptom of getting that wrong is a cache that never hits —
and publishing. A per-message failure logs the failure shape and continues; only a failure of the
consumer itself ends the loop. Before starting, call the existing topic-existence guard for the
events topic. Expose the pump task on the hub so readiness can inspect it. Provide start and stop
methods; stop cancels the task, awaits it suppressing the cancellation, then stops the consumer, in
that order, which is the sequence research executed.

Add the frame builder and the body generator. The frame is the id line, the event-name line, the
compact JSON data line and a terminating blank line. The generator subscribes, replays the requested
backlog, yields a connected comment, then loops on a TIMED wait over the queue read: a timeout yields
a heartbeat comment and continues, a message yields its frame. Cleanup lives in the generator's
`finally` — unsubscribe and decrement the gauge — with a comment recording that uvicorn closes the
generator on client disconnect and that the disconnect-polling helper reports false throughout a live
stream and deadlocks under the buffering transport.

Write `services/api/routers/feed.py` with `GET /api/feed/live` returning the streaming response with
the four headers research verified over the wire, and increment the active-connection gauge and the
sent-events counter. Add the heartbeat interval and ring size accessors to `services/api/config.py`.

Wire the hub into the lifespan in `services/api/app.py` using the existing exit stack, pushing the
hub's stop callback after the database and Redis callbacks so LIFO unwinding tears the hub down
first, and expose the hub through the lifespan state so routes reach it from the request. Extend
`services/api/routers/health.py`'s readiness response with the feed entry: the pump task exists and
is not done, and when it is done the scrubbed exception is reported — a background task that raised
is done with an exception nobody retrieved, which is the failure this check exists for.

Write `tests/unit/test_feed_consumer_config.py` asserting the factory's three settings, mirroring the
existing consumer-config test. Write `tests/integration/test_sse_live.py` against the live in-process
server: the connected comment, the SC3 measurement, the frame structure, the four response headers,
the heartbeat with a short configured interval, and the disconnect cleanup. For the latency test,
wait on the hub's own readiness — a non-empty assignment and one successful position call — rather
than on a bare sleep, so the assertion is not timing-dependent on a loaded machine; the module
docstring states that this file uses the live-server tier and why the buffering tier cannot express
any of these assertions.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_feed_consumer_config.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_sse_live.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_sse_live.py -q -p no:cacheprovider` exits 0, including the test that asserts first-byte latency under 500 ms.
    - `uv run pytest tests/unit/test_feed_consumer_config.py -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "from services.api.app import create_app; print('/api/feed/live' in {getattr(r,'path','') for r in create_app().routes})"` prints `True`.
    - `uv run python -c "import inspect, shared.kafka as k; src=[l for l in inspect.getsource(k).splitlines() if not l.strip().startswith('#')]; j=chr(10).join(src); print(j.count('group_id=None')+j.count('group_id = None'))"` prints at least `1`.
    - `uv run python -c "import services.api.sse as s; import inspect; print(not inspect.iscoroutinefunction(s.FeedHub.publish))"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>An event produced to Kafka is decoded, enriched, multicast and written to a real HTTP client's socket inside the SC3 budget, measured against a real server; the connection heartbeats, cleans up on disconnect, and a dead pump is visible to readiness.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Replay, hydration and back-pressure — Last-Event-ID, /api/feed/recent with its database fallback, and drop-oldest semantics</name>
  <files>services/api/sse.py, services/api/routers/feed.py, services/api/schemas.py, tests/unit/test_sse_framing.py, tests/unit/test_feed_hub.py, tests/unit/test_api_async_only.py, tests/integration/test_sse_live.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Server-Sent Events (executed)" — the replay transcript for all three cases, the recent-endpoint clamping result, and the ordering note for the fallback query
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Architecture Patterns" Pattern 2 (the executed seven-into-four drop transcript showing the ring unaffected) and §"Common Pitfalls" Pitfall 3
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-98
    - services/api/sse.py and services/api/routers/feed.py as written in Task 1
    - shared/db.py lines 110-140 (`AvailabilityEvent`, its composite primary key and the time column the fallback orders by)
    - tests/unit/test_no_inline_sleep.py (the template for the heartbeat gate and its non-vacuity companion)
    - tests/unit/test_api_async_only.py as written in 05-01 (extend it; do not create a second gate module)
  </read_first>
  <behavior>
    - Seven items published into a four-slot queue leave the four most recent in the queue, increment the drop counter by three, and leave all seven in the ring buffer.
    - A drop on one connection's queue leaves every other connection's queue untouched.
    - Replay after a known id returns exactly the items after it, in order.
    - Replay after an id that is not in the ring returns the whole ring.
    - Replay with no id returns nothing.
    - The last-event id is read from the header when present and from the query parameter otherwise, and a reconnect after a real disconnect receives the events it missed before live streaming resumes.
    - The frame bytes match the wire format exactly, including the terminating blank line, and the heartbeat is a comment line.
    - The recent endpoint clamps an oversized limit to the maximum and returns the last N of the ring.
    - On a process whose ring is empty, the recent endpoint returns the most recent rows from the events table in descending time order.
    - A source scan of the feed module finds no sleep-based heartbeat loop.
  </behavior>
  <action>
Complete the hub's replay and hydration surface in `services/api/sse.py`. The replay helper returns
the items after a given id, the whole ring when the id is unknown, and nothing when no id was given.
Put the design decision in the docstring, because it looks like a bug otherwise: replaying the whole
buffer for an unknown id is deliberate, since a live activity feed prefers a few duplicates that the
browser deduplicates on event id over a silent gap, and this is the case that occurs when a client
was offline longer than the ring is deep.

Add the hydration reader: it serves the last N of the ring with the limit clamped to the documented
maximum, and falls back to the events table when the ring cannot answer — ordered by the time column
descending, which is the correct order for that table's composite key. Put Pitfall 3's consequence in
the comment: the ring is per process, so two replicas hold two different recents, and the database is
the only consistent answer. Add the recent route to `services/api/routers/feed.py`, reading the
last-event id from the header first and the query parameter second, so a browser reconnect and a
hand-rolled client or a curl demo both work.

Add the feed response models to `services/api/schemas.py` so the recent endpoint is typed and appears
correctly in the OpenAPI document the Phase 6 client generates from.

Write `tests/unit/test_sse_framing.py` asserting the exact frame bytes for a representative event,
the heartbeat comment bytes, and that the data payload is one line with no embedded newline — a
multi-line payload would be parsed as several fields by any conforming client. Write
`tests/unit/test_feed_hub.py` covering the drop transcript, the ring-unaffected property, the
per-connection isolation, and all three replay cases. Extend `tests/unit/test_api_async_only.py` with
the heartbeat gate scoped to the feed module and its non-vacuity companion, following the existing
sleep gate exactly.

Extend `tests/integration/test_sse_live.py` with the reconnect case: connect, receive events,
disconnect abruptly, publish more, reconnect carrying the last received id, and assert the missed
events arrive before the live ones. Add the cold-process fallback case for the recent endpoint by
querying it from a server whose ring has not been fed.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_sse_framing.py tests/unit/test_feed_hub.py tests/unit/test_api_async_only.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_sse_live.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_sse_framing.py tests/unit/test_feed_hub.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/integration/test_sse_live.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/unit/test_api_async_only.py -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "from services.api.app import create_app; print('/api/feed/recent' in {getattr(r,'path','') for r in create_app().routes})"` prints `True`.
    - `uv run python -c "import services.api.sse as s; print(s.sse_frame({'event_id':'x','a':1}).endswith(b'\n\n'))"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A browser that drops off the network fills its own gap on reconnect, a slow browser degrades only its own stream, and a freshly started replica can still answer "what just happened" from the database.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The public read surface — merged restaurant search and detail, and a cached stats counter</name>
  <files>services/api/routers/restaurants.py, services/api/schemas.py, services/api/config.py, services/api/app.py, shared/redis_keys.py, tests/integration/test_restaurants_api.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-100
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"SQLAlchemy 2.0 Async" — the one-slug-many-source-rows result, the `ARRAY` container-operator failure with its three working alternatives and the recommended one, and the pagination guidance with its deterministic-tiebreaker rule
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Redis side of the same contract" (the `watch:count` read shape and the missing-field-reads-as-zero rule)
    - shared/db.py lines 51-71 and 110-140 (`Restaurant` columns including the party-size array, and `AvailabilityEvent`)
    - shared/redis_keys.py (the key-registry rule, the named-symbol docstring list, and `watch_count_field`)
    - services/api/schemas.py as written in the earlier plans (`RestaurantSource`, which this task extends into the merged output model)
    - scripts/verify_seed.py (the existing query shapes over `restaurants`)
  </read_first>
  <behavior>
    - The list endpoint returns one object per slug, each carrying every source row of that slug, not one object per source row.
    - A substring query matches on name, neighbourhood or cuisine, case-insensitively.
    - The exact neighbourhood, cuisine and price-tier filters each narrow the result, and combining them narrows further.
    - An oversized limit is clamped to the documented maximum; a limit of one with successive offsets walks every row exactly once with no row appearing twice, including when two restaurants share a name.
    - The party-size filter returns restaurants whose array contains the requested size and excludes those that do not, without raising.
    - Each returned restaurant carries its active watch count from the count hash, reading a missing field as zero.
    - The detail endpoint returns the merged object plus its most recent events across all its source rows; an unknown slug returns 404.
    - The stats endpoint returns the four counters; a second call within the cache window returns the same values without re-querying, and a call after the window refreshes them.
    - The stats endpoint answers with fresh values when the cache is unavailable rather than failing.
  </behavior>
  <action>
Add the stats cache key to `shared/redis_keys.py` with its TTL constant and a named-symbol docstring
entry, because every Redis key in this repository lives in that one module by rule.

Write `services/api/routers/restaurants.py` with the three D-100 routes. The list route accepts the
substring query, the three exact filters, the optional party size and the limit and offset, clamping
the limit through the framework's own bounded query parameter rather than by hand. Order by a
deterministic pair — the display order plus the primary key — with a comment stating that ordering by
the display column alone lets a row with a duplicate value appear on two pages. Use scalar membership
for the party-size test rather than the array container operator, which raises for the generic array
type this column is declared with; put the reproduced error in the comment so no one "simplifies" it
back, and note that changing the column's declared type is a shared-schema change with its own
verification, not something this route may do.

Merge the source rows into one logical restaurant per slug: group the rows, expose the source list,
and read the active watch count from the count hash using the same field helper the writer uses,
treating a missing field as zero. The detail route adds the most recent events across every source
row of the slug and answers 404 for an unknown one. Add the merged response models to
`services/api/schemas.py`, and add a comment naming the two sub-routes Phase 6 adds under the detail
path so the extension point is documented.

Write the stats route: the active watch count, the 24-hour event count, the 24-hour notification
count and the restaurant count, computed in as few statements as the shapes allow, cached in Redis
for the configured window through the new key. A cache read or write failure logs and falls through
to the live computation — a social-proof counter must never be the reason a page fails to render.

Write `tests/integration/test_restaurants_api.py` covering every `<behavior>` bullet. Seed a fixture
set that includes a slug with two source rows, two restaurants sharing a display value so the
pagination tiebreaker is actually exercised, and one restaurant with no watches so the missing-field
read is covered. Assert the cache behaviour by reading the stats twice and then advancing past the
window.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_restaurants_api.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_restaurants_api.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.app import create_app; print(sorted(p for p in {getattr(r,'path','') for r in create_app().routes} if p.startswith('/api/restaurants') or p=='/api/stats'))"` prints `['/api/restaurants', '/api/restaurants/{slug}', '/api/stats']`.
    - `cat services/api/routers/restaurants.py | grep -v '^\s*#' | grep -c 'any_'` prints at least `1`.
    - `uv run python -c "import shared.redis_keys as k; print(any('stats' in n for n in dir(k)))"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One slug reads back as one restaurant carrying every source it is watched on and its live watch count, search and pagination are deterministic, and the social-proof counter is cheap and cannot fail a page.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (05-05 slice)

**New modules:** `services/api/sse.py`, `services/api/routers/feed.py`,
`services/api/routers/restaurants.py`.

**Modified modules:** `shared/kafka.py`, `shared/redis_keys.py`, `services/api/routers/health.py`,
`services/api/schemas.py`, `services/api/config.py`, `services/api/app.py`.

**HTTP routes:** `GET /api/feed/live` (200, `text/event-stream`, chunked),
`GET /api/feed/recent?limit=` (200, clamped to 50), `GET /api/restaurants` (200, filtered and
paginated), `GET /api/restaurants/{slug}` (200 / 404), `GET /api/stats` (200, 30 s cache).
`GET /readyz` gains a `feed` entry.

**New symbols — `services/api/sse.py`:** `FeedHub`, `sse_frame`, `sse_body`, `SSE_HEADERS`,
`HEARTBEAT_SECONDS`, `RING_SIZE`.

**New symbols — `shared/kafka.py`:** the groupless consumer factory for the feed.

**New symbols — `shared/redis_keys.py`:** the stats cache key helper and its TTL constant.

**New symbols — `services/api/schemas.py`:** `FeedEventOut`, `RecentFeedResponse`,
`RestaurantOut`, `RestaurantDetailOut`, `StatsOut`.

**SSE wire contract:** `id: {event_id}`, `event: slot_opened`, `data: {compact json}`, blank-line
terminated; `: ping` comment every 15 s; `: connected` on open. `Last-Event-ID` accepted as a header
or as a `last_event_id` query parameter.

**Response headers on the feed:** `Cache-Control: no-cache`, `X-Accel-Buffering: no`,
`Connection: keep-alive`, `Content-Type: text/event-stream`.

**Env vars introduced:** `SSE_HEARTBEAT_SECONDS`, `FEED_RING_SIZE`, `STATS_CACHE_SECONDS`.
Documented in `.env.example` by 05-06.

**Metrics incremented:** `sse_connections_active`, `sse_events_sent_total`, `sse_dropped_total`,
`sse_pump_errors_total`.

**Kafka topic consumed:** `availability.events`, groupless, latest offset, never committed.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Kafka -> the feed pump | Broker-supplied bytes; a producer defect becomes a decode failure inside our process |
| the feed -> every anonymous browser | An unauthenticated broadcast channel; whatever reaches it is public |
| anonymous internet -> `/api/feed/live` | A long-lived connection is a held resource |
| anonymous internet -> the public read routes | Attacker-controlled filters and pagination against the database |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-05-35 | Information Disclosure | user-scoped data leaking onto the public broadcast channel | critical | mitigate | The pump reads only the availability topic and the enrichment adds only public restaurant fields; no watch, user, email, phone or notification row is reachable from this code path |
| T-05-36 | Denial of Service | one slow client stalling the pump and every other client's feed | high | mitigate | The publish path is synchronous and never awaits; a full queue drops that connection's oldest item and increments a counter, proven by the seven-into-four unit case |
| T-05-37 | Denial of Service | connection exhaustion from many open streams | medium | accept | Per-instance concurrency bounds it at the platform level in Phase 7; each connection costs one bounded queue and no database handle |
| T-05-38 | Denial of Service | a malformed message killing the pump and silently stopping every feed | high | mitigate | Per-message failures are logged by shape and skipped; a dead pump is surfaced by readiness with its scrubbed exception |
| T-05-39 | Tampering | a group id added to the feed consumer, splitting events across replicas | high | mitigate | The factory sets no group id, a unit test asserts all three settings, and the reason a reader would otherwise "fix" the pairing is stated in the code |
| T-05-40 | Denial of Service | an unbounded limit or offset scanning the whole events table | medium | mitigate | Limits are clamped by the framework's bounded query parameters on both the recent and the list routes |
| T-05-41 | Tampering | SQL injection through the substring or filter parameters | high | mitigate | Every query is built through the ORM with bound parameters; no string interpolation reaches the database |
| T-05-42 | Information Disclosure | a long-lived stream poisoning the public latency histogram and misrepresenting service health | low | mitigate | The streaming-duration exclusion configured in 05-01 is verified here against a real connection |
| T-05-43 | Information Disclosure | the availability feed revealing restaurant demand | low | accept | The data is public by definition — it is what the site displays — and this is the same posture the README's legal section already documents |
| T-05-SC | Tampering | package-manager installs | high | mitigate | Zero packages added; the streaming response, the consumer and the exposition all come from libraries already pinned and already imported by shipped code |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run pytest tests/integration/test_sse_live.py -q -p no:cacheprovider` exits 0 — SC3 measured locally; the same measurement through the deployed URL is the pending-human Phase 7 runbook item.
</verification>

<success_criteria>
- One consumer per process feeds every connected client, and adding a group id would be caught by a unit test.
- An event published to Kafka reaches a real HTTP client inside the SC3 budget, measured through a real server.
- A slow client degrades only its own stream; a reconnecting client fills its own gap; a fresh replica can still answer from the database.
- The feed heartbeats without a sleep loop and cleans up on disconnect.
- One slug reads back as one restaurant with its sources, its live watch count and its recent events, and search paginates deterministically.
</success_criteria>

<output>
Create `.planning/phases/05-api-watchlist-crud-sse/05-05-SUMMARY.md` when done
</output>
