"""State machine service entry point (D-42, D-43, D-46, D-47a).

Mirrors services/poller/main.py: startup topic guard, every async resource constructed INSIDE
``run()``, and an ``AsyncExitStack`` so a partial startup tears down exactly what it managed to
acquire. The construction site matters — ``AIOKafkaConsumer``
calls ``get_running_loop()`` in its constructor and raises if it is built at module import
time (research B-1).

Startup guard 1: all 5 Named-Symbol Kafka topics must exist, because auto-creation is disabled
and a missing topic would otherwise fail silently per-publish (D-27).
Startup guard 2: the test-only crash hook is refused unless ENV is EXPLICITLY one of the
dev/test/ci/local allowlist — a safety interlock has to fail closed (T-02-04).

Shutdown: SIGTERM/SIGINT are turned into task cancellation by ``shared.shutdown``, so the
exit stack unwinds instead of the process being terminated where it stands (WR-02).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack

import redis.asyncio as redis
from aiokafka.admin import AIOKafkaAdminClient

from services.state_machine.config import (
    CONFIRM_DELAY_MS,
    CONSUMER_GROUP_ID,
    CRASH_HOOK_ENVS,
    crash_after,
    crash_hook_allowed,
    kafka_bootstrap_servers,
    redis_url,
)
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.store import BufferedStateStore, RedisStateStore
from shared.db import dispose_engine
from shared.kafka import make_consumer, make_producer
from shared.scheduler.lua import LuaScheduler
from shared.shutdown import run_until_signal
from shared.telemetry import configure_logging, get_logger

log = get_logger(__name__)

# Named-Symbol Kafka topics — the same set services/poller/main.py guards on. Declared here
# rather than imported from the poller: importing that module would drag in its config, which
# freezes the Redis/Kafka URLs at import time, and its shared httpx client singleton.
REQUIRED_TOPICS: set[str] = {
    "availability.raw",
    "availability.events",
    "polls.completed",
    "notifications.queued",
    "notifications.sent",
}


async def _assert_topics_exist(bootstrap_servers: str) -> None:
    """Startup guard: refuse to run if any required topic is missing (D-27)."""
    # `start()` INSIDE the try (IN-02): a broker that accepts the socket and then fails the
    # metadata handshake left the client's connections open, which is the same leak WR-04
    # fixed one level up. `close()` is safe on a client that never finished starting.
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    try:
        await admin.start()
        existing = set(await admin.list_topics())
    finally:
        await admin.close()
    missing = REQUIRED_TOPICS - existing
    if missing:
        raise RuntimeError(
            f"Kafka topics missing: {sorted(missing)}. Run `make topics` first."
        )


async def run() -> None:
    configure_logging()

    # Fail CLOSED (T-02-04). The old guard was `env_name() == "prod"`, which armed a SIGKILL
    # hook on a live event pipeline for ENV=production, ENV=PROD, and any container that
    # forgot to set ENV at all — the unconfigured case being the most permissive one.
    if crash_after() is not None and not crash_hook_allowed():
        raise RuntimeError(
            f"MISE_CRASH_AFTER is set but ENV={os.getenv('ENV')!r} is not one of "
            f"{sorted(CRASH_HOOK_ENVS)}. That variable is a TEST-ONLY hook that SIGKILLs this "
            "process at the named stage (T-02-04); unset it, or set ENV explicitly to a "
            "non-production environment."
        )

    bootstrap_servers = kafka_bootstrap_servers()
    url = redis_url()
    log.info("state_machine_starting")

    # AsyncExitStack, not a single try/finally at the end: every acquisition below can fail
    # (a missing topic is the documented `_assert_topics_exist` path), and with one late
    # try/finally a failure there leaked the Redis connection, and a failure in
    # `make_consumer` leaked a started producer too. Registering each resource the moment it
    # exists makes the teardown match the docstring. Unwinding is LIFO — consumer, producer,
    # Redis — which is the order the previous `finally` used.
    try:
        async with AsyncExitStack() as stack:
            # persistence.py creates the SQLAlchemy engine lazily on its first write, so
            # nothing else ever disposes it. Registered before anything is acquired, which
            # under LIFO unwinding makes it the LAST thing torn down: the asyncpg pool is
            # then closed against a live loop instead of being garbage-collected against a
            # closing one ("Event loop is closed", unclosed connections, server-side
            # sessions left to time out). A no-op when no write ever happened.
            stack.push_async_callback(dispose_engine)

            r = redis.from_url(url)
            stack.push_async_callback(r.aclose)

            scheduler = LuaScheduler(r)
            await scheduler.start()

            # Precondition: all 5 Named-Symbol topics must exist (D-27).
            await _assert_topics_exist(bootstrap_servers)

            producer = await make_producer(bootstrap_servers)
            stack.push_async_callback(producer.stop)

            consumer = await make_consumer(
                "availability.raw",
                "polls.completed",
                group_id=CONSUMER_GROUP_ID,
                bootstrap_servers=bootstrap_servers,
            )
            stack.push_async_callback(consumer.stop)

            durable_store = RedisStateStore(r)
            buffer = BufferedStateStore(durable_store)
            engine = DiffEngine(buffer, confirm_delay_ms=CONFIRM_DELAY_MS)
            state_machine = StateMachineConsumer(
                consumer=consumer,
                producer=producer,
                redis_client=r,
                scheduler=scheduler,
                engine=engine,
                store=durable_store,
                buffer=buffer,
            )

            log.info(
                "state_machine_ready",
                redis=url,
                kafka=bootstrap_servers,
                group_id=CONSUMER_GROUP_ID,
                confirm_delay_ms=CONFIRM_DELAY_MS,
            )

            # SIGTERM must unwind the stack, not kill the process where it stands (WR-02).
            # `docker stop`, `make down`, a Kubernetes eviction and the chaos test's own
            # `terminate()` all send SIGTERM, and Python's default disposition would end the
            # process before `consumer.stop()`, `producer.stop()`, `r.aclose()` and
            # `dispose_engine()` could run — the last of which shared/db.py documents as
            # mandatory. The producer's 20 ms linger batch was dropped rather than flushed.
            await run_until_signal(state_machine.run())
    finally:
        log.info("state_machine_stopped")


if __name__ == "__main__":
    asyncio.run(run())
