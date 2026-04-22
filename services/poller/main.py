"""Poller service entry point (D-05, D-08).

The shared :class:`httpx.AsyncClient` is obtained from
:mod:`shared.http_client` — never constructed per-poll (Pitfall 9).
Runs :func:`poll_loop` and :func:`reaper_loop` concurrently via
:func:`asyncio.gather`.

Startup guard: refuses to enter the poll loop unless all 5 Named-Symbol
Kafka topics exist — Plan 02 disables ``auto.create.topics.enable`` so a
missing topic would otherwise fail silently per-publish (D-27).
"""
from __future__ import annotations

import asyncio

import redis.asyncio as redis
from aiokafka.admin import AIOKafkaAdminClient

from services.poller.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    REDIS_URL,
)
from services.poller.publisher import Publisher
from services.poller.reaper import reaper_loop
from services.poller.scheduler import poll_loop
from services.poller.sources.opentable.adapter import OpenTableAdapter
from shared.http_client import close_async_client, get_async_client
from shared.kafka import make_producer
from shared.scheduler.lua import LuaScheduler
from shared.telemetry import configure_logging, get_logger

log = get_logger(__name__)

# Named-Symbol Kafka topics — must match scripts/create_topics.py and
# 01-RESEARCH.md §Named Symbols -> Kafka topics (D-27).
REQUIRED_TOPICS: set[str] = {
    "availability.raw",
    "availability.events",
    "polls.completed",
    "notifications.queued",
    "notifications.sent",
}


async def _assert_topics_exist(bootstrap_servers: str) -> None:
    """Startup guard: refuse to run if any required topic is missing.

    Plan 02 sets ``KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE=false``, so a missing
    topic would otherwise fail silently per-publish. Fail fast instead with
    a clear remediation message (D-27).
    """
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
    log.info("poller_starting")

    # Shared httpx.AsyncClient (D-05, Pitfall 9 — ONE client per process
    # via shared.http_client singleton). close_async_client() is idempotent
    # so the outer finally block is safe even if inner setup raises.
    http_client = get_async_client()
    try:
        # Connect to Redis.
        r = redis.from_url(REDIS_URL)
        scheduler = LuaScheduler(r)
        await scheduler.start()

        # Precondition: all 5 Named-Symbol topics must exist (D-27).
        await _assert_topics_exist(KAFKA_BOOTSTRAP_SERVERS)

        # Connect to Kafka.
        producer = await make_producer(KAFKA_BOOTSTRAP_SERVERS)

        # Wire adapters — each uses the shared client singleton.
        opentable = OpenTableAdapter(client=http_client)
        publisher = Publisher(producer=producer)

        log.info(
            "poller_ready",
            redis=REDIS_URL,
            kafka=KAFKA_BOOTSTRAP_SERVERS,
        )

        try:
            await asyncio.gather(
                poll_loop(scheduler, opentable, publisher),
                reaper_loop(scheduler),
            )
        finally:
            await producer.stop()
            await r.aclose()
            log.info("poller_stopped")
    finally:
        await close_async_client()


if __name__ == "__main__":
    asyncio.run(run())
