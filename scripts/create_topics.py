#!/usr/bin/env python
"""
Idempotent Kafka topic creation for Mise en Place (D-27).
Run: uv run python scripts/create_topics.py
Or:  make topics

Topics and retention:
  availability.raw      1 partition, 24h  (86_400_000 ms)
  availability.events   1 partition, 7d   (604_800_000 ms)
  polls.completed       1 partition, 7d   (604_800_000 ms)
  notifications.queued  1 partition, 30d  (2_592_000_000 ms)
  notifications.sent    1 partition, 30d  (2_592_000_000 ms)

Named Symbols (D-27, D-28, D-29):
  Kafka topics: availability.raw, availability.events, notifications.queued,
                notifications.sent, polls.completed
  Message key: {source}:{restaurant_id}
  Replication factor: 1 (MVP single-broker; documented tradeoff in README, Pitfall 11)
"""
import asyncio
import os

from aiokafka.admin import AIOKafkaAdminClient, NewTopic


BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")

TOPICS = [
    NewTopic(
        "availability.raw",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(86_400_000)},       # 24h
    ),
    NewTopic(
        "availability.events",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(604_800_000)},      # 7d
    ),
    NewTopic(
        "polls.completed",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(604_800_000)},      # 7d
    ),
    NewTopic(
        "notifications.queued",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(2_592_000_000)},    # 30d
    ),
    NewTopic(
        "notifications.sent",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(2_592_000_000)},    # 30d
    ),
]


async def main() -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        existing: set[str] = set(await admin.list_topics())
        to_create = [t for t in TOPICS if t.name not in existing]
        if to_create:
            await admin.create_topics(to_create)
            print(f"Created topics: {[t.name for t in to_create]}")
        else:
            print("All topics already exist — idempotent no-op")
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
