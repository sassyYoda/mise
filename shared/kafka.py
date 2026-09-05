"""
AIOKafka producer/consumer factories for Mise en Place (D-02, D-47a).
Named producer config: acks='all', enable_idempotence=True, compression_type='gzip', linger_ms=20.
Named consumer config: enable_auto_commit=False, auto_offset_reset='earliest', max_poll_records=1.
All producers and consumers are created via these factories — no inline instantiation
in services. Named symbols: make_producer, make_consumer.
"""
from __future__ import annotations

import os

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer


async def make_producer(bootstrap_servers: str | None = None) -> AIOKafkaProducer:
    """
    Create and start an AIOKafkaProducer with correct durability config (D-02, Pitfall 11).

    Args:
        bootstrap_servers: Comma-separated Kafka brokers. Defaults to KAFKA_BOOTSTRAP_SERVERS env var.

    Returns:
        A started AIOKafkaProducer. Caller is responsible for .stop() on shutdown.
    """
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
    producer = AIOKafkaProducer(
        bootstrap_servers=servers,
        acks="all",                                   # D-02: wait for all in-sync replicas
        enable_idempotence=True,                      # prevents duplicates on retry
        # NOTE: aiokafka has no max_in_flight_requests_per_connection kwarg; it
        # enforces the idempotence-safe in-flight limit internally.
        compression_type="gzip",                      # cheap at ~10KB messages
        linger_ms=20,                                  # small batching window
        request_timeout_ms=30_000,
        value_serializer=lambda v: v if isinstance(v, bytes) else v.encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )
    await producer.start()
    return producer



async def make_consumer(
    *topics: str,
    group_id: str,
    bootstrap_servers: str | None = None,
) -> AIOKafkaConsumer:
    """
    Create and start a manual-commit consumer (D-47a, Pitfall 4/10).

    MUST be called from inside a running event loop: ``AIOKafkaConsumer.__init__``
    calls ``get_running_loop()`` and raises ``RuntimeError`` otherwise. Being an
    ``async def`` factory, this function structurally cannot be called at import time.

    Topics are *varargs*. Passing a list raises ``TypeError: unhashable type: 'list'``
    because aiokafka declares ``def __init__(self, *topics, ...)`` (research B-1).

    Args:
        *topics: Topic names, e.g. ``make_consumer("availability.raw", "polls.completed", ...)``.
        group_id: Consumer group id.
        bootstrap_servers: Comma-separated Kafka brokers. Defaults to KAFKA_BOOTSTRAP_SERVERS.

    Returns:
        A started AIOKafkaConsumer. Caller is responsible for .stop() on shutdown.
    """
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=servers,
        group_id=group_id,
        enable_auto_commit=False,               # Pitfall 4 — manual commit only
        auto_offset_reset="earliest",           # D-47a
        max_poll_records=1,                     # Pitfall 10 — one message at a time
        isolation_level="read_uncommitted",
        # No value_deserializer: the shell wants raw bytes so the replay path and the
        # wire format share one serializer (Pitfall 7).
        # NOTE: as with make_producer, aiokafka has no
        # max_in_flight_requests_per_connection kwarg — do not reintroduce it.
    )
    await consumer.start()
    return consumer
