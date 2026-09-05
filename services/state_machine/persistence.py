"""
TimescaleDB persistence for confirmed availability events (D-48, D-48a; STATE-05).

Both writes are BEST EFFORT by design: a Postgres stall is logged and swallowed so it can never
block the Kafka emit or the offset commit — a delivered notification beats a durable analytics
row (D-48). Both statements name `time` alongside `event_id`, because a hypertable unique index
must include the partitioning column and a predicate that omits it degrades from a single-chunk
index scan to a bitmap scan across every chunk (research B-2, B-3, verified EXPLAIN).
Named symbols: hours_before_service, day_of_week, epoch_ms_to_utc, insert_event, close_event
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, func, literal, update
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.db import AvailabilityEvent as AvailabilityEventRow
from shared.db import get_async_session
from shared.events import AvailabilityEvent
from shared.telemetry import get_logger

log = get_logger(__name__)

# Service times are local to the restaurant; every mise restaurant is in NYC (PROJECT.md).
_SERVICE_TZ = ZoneInfo("America/New_York")


def epoch_ms_to_utc(epoch_ms: int) -> datetime:
    """Convert a wire timestamp to an aware UTC datetime for the hypertable."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


def hours_before_service(service_date: date, slot: dt_time, first_seen_ms: int) -> float:
    """
    Lead time in hours from the first sighting (UTC) to the service datetime (New York local).

    Assumes dinner service, 17:00-23:00 local, which is why no fold handling is needed: a
    service time never lands inside the 01:00-03:00 daylight-saving transition window, so the
    non-existent and the ambiguous local times are both unreachable in this domain
    (research Pattern 6, assumption A4).
    """
    service_dt = datetime.combine(service_date, slot, tzinfo=_SERVICE_TZ)
    first_seen = datetime.fromtimestamp(first_seen_ms / 1000, tz=UTC)
    return (service_dt - first_seen).total_seconds() / 3600.0


def day_of_week(service_date: date) -> int:
    """0=Sun .. 6=Sat — the Phase 6 heatmap y-axis and migration 0008's column comment (B-5)."""
    return service_date.isoweekday() % 7


def _parse_time_slot(value: str) -> dt_time | None:
    """Tolerant `HH:MM` / `HH:MM:SS` parse; an unreadable slot stores NULL instead of failing."""
    try:
        return dt_time.fromisoformat(value)
    except ValueError:
        return None


async def insert_event(event: AvailabilityEvent) -> None:
    """
    Persist one confirmed event, idempotently (STATE-05).

    The arbiter names both index columns, so replaying the same event leaves exactly one row.
    Two slots confirmed by the same poll share `time` and still write two rows, because the
    uniqueness is on `(event_id, time)` and their event ids differ (research B-3).
    """
    try:
        service_date = date.fromisoformat(event.date)
        slot = _parse_time_slot(event.time_slot)
        confirmed_at = epoch_ms_to_utc(event.confirmed_at_epoch_ms)
        values: dict[str, Any] = {
            "time": confirmed_at,
            "event_id": event.event_id,
            "restaurant_id": event.restaurant_id,
            "source": event.source,
            "date": service_date,
            "time_slot": slot,
            "party_size": event.party_size,
            "seat_type": event.seat_type,
            "booking_token": event.booking_token,
            "first_seen_at": epoch_ms_to_utc(event.first_seen_at_epoch_ms),
            "last_seen_at": confirmed_at,
            "hours_before_service": (
                None
                if slot is None
                else hours_before_service(service_date, slot, event.first_seen_at_epoch_ms)
            ),
            "day_of_week": day_of_week(service_date),
        }
        statement = (
            pg_insert(AvailabilityEventRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["event_id", "time"])
        )
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(statement)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best effort: never block the emit or the commit
        log.error(
            "availability_event_insert_failed",
            event_id=str(event.event_id),
            restaurant_id=event.restaurant_id,
            error=str(exc),
        )


async def close_event(event_id: UUID, confirmed_at: datetime, last_seen_at: datetime) -> None:
    """
    Stamp `last_seen_at` and `duration_seconds` on a slot that vanished (D-45, D-48).

    The duration is computed IN SQL from the row's own stored `first_seen_at`, so a close can
    never disagree with the insert that created the row, whatever the caller believes. Closures
    are database-only: nothing goes to Kafka (D-45).
    """
    try:
        statement = (
            update(AvailabilityEventRow)
            .where(
                AvailabilityEventRow.event_id == event_id,
                AvailabilityEventRow.time == confirmed_at,
            )
            .values(
                last_seen_at=last_seen_at,
                duration_seconds=sa_cast(
                    func.extract(
                        "epoch",
                        literal(last_seen_at) - AvailabilityEventRow.first_seen_at,
                    ),
                    Integer,
                ),
            )
        )
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(statement)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best effort: a stalled close never stalls Kafka
        log.error(
            "availability_event_close_failed",
            event_id=str(event_id),
            error=str(exc),
        )
