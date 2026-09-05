"""State machine service entry point (D-42, D-43, D-46, D-47a).

Mirrors services/poller/main.py: startup topic guard, every async resource constructed INSIDE
``run()``, and an ``AsyncExitStack`` so a partial startup tears down exactly what it managed to
acquire. The construction site matters — ``AIOKafkaConsumer``
calls ``get_running_loop()`` in its constructor and raises if it is built at module import
time (research B-1).

Startup guard 1: all 5 Named-Symbol Kafka topics must exist, because auto-creation is disabled
and a missing topic would otherwise fail silently per-publish (D-27).
Startup guard 2: the test-only crash hook is refused outright in prod (T-02-04).
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

import redis.asyncio as redis
from aiokafka.admin import AIOKafkaAdminClient

from services.state_machine.config import (
    CONFIRM_DELAY_MS,
    CONSUMER_GROUP_ID,
    crash_after,
    env_name,
    kafka_bootstrap_servers,
    redis_url,
)
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.store import BufferedStateStore, RedisStateStore
from shared.kafka import make_consumer, make_producer
from shared.scheduler.lua import LuaScheduler
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
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
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

    if crash_after() is not None and env_name() == "prod":
        raise RuntimeError(
            "MISE_CRASH_AFTER is set and ENV=prod. That variable is a TEST-ONLY hook that "
            "SIGKILLs this process at the named stage (T-02-04); unset it to start."
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

            await state_machine.run()
    finally:
        log.info("state_machine_stopped")


if __name__ == "__main__":
    asyncio.run(run())
