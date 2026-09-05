"""Integration: STATE-05 — the analytics write path against a live TimescaleDB hypertable.

Covers ROADMAP Phase 2 success criterion 4 at the persistence tier: two slots confirmed by one
poll write two rows sharing a ``time`` (research B-3), a replayed insert leaves exactly one row,
a close stamps ``duration_seconds`` from the row's own ``first_seen_at`` and touches nothing
else, and a Postgres outage is logged rather than raised so the Kafka emit is never blocked
(D-48).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest

from services.state_machine.persistence import close_event, insert_event
from shared.events import AvailabilityEvent, make_event_id
from tests.integration.conftest import apply_migrations, reset_shared_db_singletons

pytestmark = pytest.mark.integration

RID = 4242
DATE = "2026-05-01"
PARTY = 2
FIRST_SEEN_MS = int(datetime(2026, 5, 1, 18, 0, tzinfo=UTC).timestamp() * 1000)
CONFIRMED_MS = int(datetime(2026, 5, 1, 18, 0, 30, tzinfo=UTC).timestamp() * 1000)
CONFIRMED_AT = datetime(2026, 5, 1, 18, 0, 30, tzinfo=UTC)


def _event(seat_type: str, *, first_poll_id: str = "poll-a") -> AvailabilityEvent:
    """One confirmed event. Two seat types at the same time are two distinct slots (D-36)."""
    slot_key = f"19:00|{seat_type}"
    return AvailabilityEvent(
        event_id=make_event_id("opentable", RID, DATE, PARTY, slot_key, first_poll_id),
        event_type="slot_opened",
        source="opentable",
        restaurant_id=RID,
        date=DATE,
        time_slot="19:00",
        party_size=PARTY,
        seat_type=seat_type,
        booking_token=f"token-{seat_type}",
        first_seen_at_epoch_ms=FIRST_SEEN_MS,
        confirmed_at_epoch_ms=CONFIRMED_MS,
        produced_at_epoch_ms=CONFIRMED_MS,
        confirming_poll_id=UUID(int=7),
    )


@pytest.fixture(scope="module", autouse=True)
def _migrated_and_wired(db_urls):
    """Point shared.db at this module's container and apply every migration once.

    The environment is patched through a MonkeyPatch context, not assigned into os.environ:
    an unrestored DATABASE_URL_* leaks into every later test in the session, silently binding
    anything that reads it to a container that has already been torn down. That is an
    order-dependent failure that only shows up when the suite runs in a different order
    (WR-15). `pytest.MonkeyPatch.context()` is the module-scoped equivalent of the
    function-scoped `monkeypatch` fixture.
    """
    apply_migrations({**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]})
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL_ASYNC", db_urls["async"])
        mp.setenv("DATABASE_URL_SYNC", db_urls["sync"])
        reset_shared_db_singletons()
        yield
    reset_shared_db_singletons()


@pytest.fixture(autouse=True)
async def _clean_rows(db_urls):
    """Every test starts from an empty table and a fresh engine.

    The reset is per-test, not per-module: pytest-asyncio gives each test its own event loop,
    and a cached SQLAlchemy engine holds asyncpg connections bound to the previous one
    ("attached to a different loop"). Rebuilding the singleton binds it to the live loop.
    """
    reset_shared_db_singletons()
    conn = await asyncpg.connect(db_urls["dsn"])
    await conn.execute("DELETE FROM availability_events WHERE restaurant_id = $1", RID)
    await conn.close()
    yield


async def _rows(dsn: str):
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(
            'SELECT * FROM availability_events WHERE restaurant_id = $1 ORDER BY seat_type, "time"',
            RID,
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_two_slots_from_one_poll_write_two_rows_sharing_a_time(db_urls):
    """Research B-3: the primary key is (time, event_id), so a shared confirming poll is fine."""
    bar, standard = _event("bar"), _event("standard")
    assert bar.event_id != standard.event_id

    await insert_event(bar)
    await insert_event(standard)

    rows = await _rows(db_urls["dsn"])
    assert len(rows) == 2
    assert rows[0]["time"] == rows[1]["time"], "both rows must carry the confirming poll's time"
    assert {r["event_id"] for r in rows} == {bar.event_id, standard.event_id}


@pytest.mark.asyncio
async def test_replaying_the_same_event_leaves_exactly_one_row(db_urls):
    """The arbiter names both index columns, so a redelivered emit is idempotent."""
    event = _event("bar")
    await insert_event(event)
    await insert_event(event)

    rows = await _rows(db_urls["dsn"])
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] is None, "an open slot has no duration yet"


@pytest.mark.asyncio
async def test_inserted_row_carries_the_derived_analytics_columns(db_urls):
    """first_seen_at, last_seen_at, hours_before_service and day_of_week are all populated."""
    await insert_event(_event("bar"))

    row = (await _rows(db_urls["dsn"]))[0]
    assert row["first_seen_at"] == datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
    assert row["last_seen_at"] == CONFIRMED_AT
    assert row["hours_before_service"] == pytest.approx(5.0)
    assert row["day_of_week"] == 5  # 2026-05-01 is a Friday, 0=Sun .. 6=Sat
    assert row["booking_token"] == "token-bar"


@pytest.mark.asyncio
async def test_close_stamps_duration_from_the_rows_own_first_seen_at(db_urls):
    """The close computes the duration in SQL, so it can never disagree with the insert."""
    bar, standard = _event("bar"), _event("standard")
    await insert_event(bar)
    await insert_event(standard)

    last_seen = datetime(2026, 5, 1, 19, 0, tzinfo=UTC)  # 1 h after first_seen_at
    await close_event(
        event_id=bar.event_id, confirmed_at=CONFIRMED_AT, last_seen_at=last_seen
    )

    rows = {r["event_id"]: r for r in await _rows(db_urls["dsn"])}
    assert rows[bar.event_id]["last_seen_at"] == last_seen
    assert rows[bar.event_id]["duration_seconds"] == 3600
    # The sibling slot confirmed by the same poll shares the row `time` and must be untouched.
    assert rows[standard.event_id]["duration_seconds"] is None
    assert rows[standard.event_id]["last_seen_at"] == CONFIRMED_AT


@pytest.mark.asyncio
async def test_close_with_the_wrong_time_matches_nothing(db_urls):
    """Both key columns are in the predicate; naming only event_id would scan every chunk."""
    bar = _event("bar")
    await insert_event(bar)

    await close_event(
        event_id=bar.event_id,
        confirmed_at=datetime(2026, 5, 2, 18, 0, 30, tzinfo=UTC),
        last_seen_at=datetime(2026, 5, 2, 19, 0, tzinfo=UTC),
    )

    row = (await _rows(db_urls["dsn"]))[0]
    assert row["duration_seconds"] is None


@pytest.mark.asyncio
async def test_a_database_outage_is_logged_and_never_raised(db_urls, monkeypatch):
    """D-48: metrics beat durability of the analytics row — the caller still emits and commits."""
    monkeypatch.setenv("DATABASE_URL_ASYNC", "postgresql+asyncpg://mise:mise@127.0.0.1:1/mise")
    reset_shared_db_singletons()
    try:
        # Both writes must return normally against a closed port.
        await insert_event(_event("bar"))
        await close_event(
            event_id=_event("bar").event_id,
            confirmed_at=CONFIRMED_AT,
            last_seen_at=CONFIRMED_AT,
        )
    finally:
        monkeypatch.undo()
        reset_shared_db_singletons()

    assert await _rows(db_urls["dsn"]) == [], "nothing may have been written during the outage"
