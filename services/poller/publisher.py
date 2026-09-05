"""Kafka publisher for the OpenTable poller (D-29, POLL-07).

Emits to ``availability.raw`` (on success only) and ``polls.completed``
(on every attempt), and writes a ``poll_log`` row synchronously before
returning so PERF-02 verification can rely on the row being there.

Named Symbols: ``availability.raw``, ``polls.completed``,
``{source}:{restaurant_id}``.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaProducer
from sqlalchemy import insert

from shared.db import PollLog, get_async_session
from shared.events import AvailabilityRaw, PollCompleted
from shared.telemetry import get_logger

log = get_logger(__name__)


class Publisher:
    """Emits Kafka events and persists ``poll_log`` rows (POLL-07)."""

    def __init__(self, producer: AIOKafkaProducer) -> None:
        self.producer = producer

    async def publish(
        self,
        poll_id: UUID,
        source: str,
        restaurant_id: int,
        raw_response: dict[str, Any],
        request_params: dict[str, Any],
        status: str,  # 'success' | 'error' | 'timeout'
        latency_ms: int,
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        """Emit ``availability.raw`` + ``polls.completed`` and write ``poll_log``.

        Kafka key = ``'{source}:{restaurant_id}'`` (D-29). The ``poll_log``
        write is synchronous and happens before return so callers can assume
        durability when ``publish`` resolves (POLL-07, SC4).
        """
        now_ms = int(time.time() * 1000)
        kafka_key = f"{source}:{restaurant_id}"  # Named Symbol: {source}:{restaurant_id}

        # 1. Emit availability.raw (only on success — never on error/timeout).
        if status == "success" and raw_response:
            raw_event = AvailabilityRaw(
                poll_id=poll_id,
                source=source,  # type: ignore[arg-type]
                restaurant_id=restaurant_id,
                polled_at_epoch_ms=now_ms,
                raw_response=raw_response,
                request_params=request_params,
            )
            await self.producer.send(
                "availability.raw",  # Named Symbol
                value=raw_event.to_bytes(),
                key=kafka_key,
            )
            log.info(
                "availability_raw_published",
                poll_id=str(poll_id),
                restaurant_id=restaurant_id,
            )

        # 2. Emit polls.completed (always — success, error, or timeout).
        completed_event = PollCompleted(
            poll_id=poll_id,
            source=source,  # type: ignore[arg-type]
            restaurant_id=restaurant_id,
            polled_at_epoch_ms=now_ms,
            status=status,  # type: ignore[arg-type]
            latency_ms=latency_ms,
            http_status=http_status,
            error=error,
        )
        await self.producer.send(
            "polls.completed",  # Named Symbol
            value=completed_event.to_bytes(),
            key=kafka_key,
        )

        # 3. Write poll_log row synchronously before returning (SC4, POLL-07).
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(
                insert(PollLog).values(
                    time=datetime.now(UTC),
                    restaurant_id=restaurant_id,
                    source=source,
                    status=status,
                    latency_ms=latency_ms,
                    http_status=http_status,
                    error=error,
                    poll_id=poll_id,
                )
            )
            await session.commit()

        log.debug(
            "poll_published",
            poll_id=str(poll_id),
            restaurant_id=restaurant_id,
            status=status,
            latency_ms=latency_ms,
        )
