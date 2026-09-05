"""Integration: STATE-01 — RedisStateStore against a live Redis 7.2 container (D-40, D-42).

Proves the durability contract the diff engine assumes: records round-trip through the compact
JSON codec unchanged, every write refreshes the 25-hour key TTL, dropping the last field makes
the key vanish, and both empty-input edges answer with an empty result rather than raising.

The TTL is key-level on purpose. Per-field hash TTL is a Redis 7.4 SERVER feature; redis-py
7.4.0 exposes the client method, so reaching for it would lint clean and fail only at runtime
against the pinned redis:7.2-alpine (research Pitfall 6). The last test in this file is the
standing source grep that keeps it out.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import redis.asyncio as aioredis

from services.state_machine.models import MetaRecord, SlotRecord, SlotState
from services.state_machine.store import RedisStateStore
from shared.redis_keys import AVAIL_STATE_TTL_SECONDS, avail_meta_key, avail_state_key

pytestmark = pytest.mark.integration

RID = 77
DATE = "2026-05-01"
PARTY = 2
SLOT_KEY = "19:00|bar"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _record(state: SlotState = SlotState.PENDING) -> SlotRecord:
    return SlotRecord(
        state=state,
        token="abc123-reservation-token",
        first_seen_ms=1_800_000_000_000,
        first_poll_id="6f1b1c62-0000-4000-8000-000000000001",
        last_seen_ms=1_800_000_009_000,
        confirmed_ms=1_800_000_009_000 if state is SlotState.AVAILABLE else None,
        event_id="21b2421d-b3cb-5572-9988-830d4e6c4a3c" if state is SlotState.AVAILABLE else None,
    )


async def _client(url: str) -> aioredis.Redis:
    r = aioredis.from_url(url, decode_responses=False)
    await r.delete(avail_state_key(RID, DATE, PARTY), avail_meta_key(RID))
    return r


@pytest.mark.asyncio
async def test_slot_record_round_trips_unchanged(redis_url):
    r = await _client(redis_url)
    store = RedisStateStore(r)
    try:
        record = _record(SlotState.AVAILABLE)
        await store.put_slot(RID, DATE, PARTY, SLOT_KEY, record)

        loaded = await store.get_slots(RID, DATE, PARTY)
        assert loaded == {SLOT_KEY: record}
        assert loaded[SLOT_KEY].to_json() == record.to_json()
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_every_write_refreshes_the_key_ttl(redis_url):
    """25 h, re-stamped on every mutating call — the only expiry Redis 7.2 offers here."""
    r = await _client(redis_url)
    store = RedisStateStore(r)
    try:
        await store.put_slot(RID, DATE, PARTY, SLOT_KEY, _record())
        ttl = await r.ttl(avail_state_key(RID, DATE, PARTY))
        assert AVAIL_STATE_TTL_SECONDS - 1 <= ttl <= AVAIL_STATE_TTL_SECONDS

        # Wind the TTL down, then prove a second write pushes it back up.
        await r.expire(avail_state_key(RID, DATE, PARTY), 60)
        assert await r.ttl(avail_state_key(RID, DATE, PARTY)) <= 60

        await store.put_slot(RID, DATE, PARTY, SLOT_KEY, _record(SlotState.AVAILABLE))
        refreshed = await r.ttl(avail_state_key(RID, DATE, PARTY))
        assert AVAIL_STATE_TTL_SECONDS - 1 <= refreshed <= AVAIL_STATE_TTL_SECONDS
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_dropping_the_last_field_removes_the_key(redis_url):
    r = await _client(redis_url)
    store = RedisStateStore(r)
    try:
        await store.put_slot(RID, DATE, PARTY, SLOT_KEY, _record())
        await store.put_slot(RID, DATE, PARTY, "19:30|bar", _record())

        await store.drop_slot(RID, DATE, PARTY, SLOT_KEY)
        assert set(await store.get_slots(RID, DATE, PARTY)) == {"19:30|bar"}
        assert await r.exists(avail_state_key(RID, DATE, PARTY)) == 1

        await store.drop_slot(RID, DATE, PARTY, "19:30|bar")
        assert await store.get_slots(RID, DATE, PARTY) == {}
        assert await r.exists(avail_state_key(RID, DATE, PARTY)) == 0
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_meta_round_trips_and_clears(redis_url):
    """A cleared UNKNOWN mark must not linger: one HSET fully replaces the record."""
    r = await _client(redis_url)
    store = RedisStateStore(r)
    try:
        await store.put_meta(RID, MetaRecord(unknown_since_ms=1_700, last_success_ms=1_600))
        assert await store.get_meta(RID) == MetaRecord(
            unknown_since_ms=1_700, last_success_ms=1_600
        )

        await store.put_meta(RID, MetaRecord(unknown_since_ms=None, last_success_ms=1_900))
        assert await store.get_meta(RID) == MetaRecord(
            unknown_since_ms=None, last_success_ms=1_900
        )
        ttl = await r.ttl(avail_meta_key(RID))
        assert AVAIL_STATE_TTL_SECONDS - 1 <= ttl <= AVAIL_STATE_TTL_SECONDS
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_absent_key_and_absent_restaurant_are_empty_not_errors(redis_url):
    """The empty-input edges: a fresh restaurant reads as no slots and an unmarked meta."""
    r = await _client(redis_url)
    store = RedisStateStore(r)
    try:
        assert await store.get_slots(RID, "2099-01-01", 8) == {}
        assert await store.get_meta(987_654) == MetaRecord(
            unknown_since_ms=None, last_success_ms=None
        )
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_an_unreadable_field_is_skipped_not_raised(redis_url):
    """A corrupt hash field must not halt the partition; the slot simply re-enters PENDING."""
    r = await _client(redis_url)
    store = RedisStateStore(r)
    try:
        await store.put_slot(RID, DATE, PARTY, SLOT_KEY, _record())
        await r.hset(avail_state_key(RID, DATE, PARTY), "19:30|bar", b"{not json")

        loaded = await store.get_slots(RID, DATE, PARTY)
        assert set(loaded) == {SLOT_KEY}
    finally:
        await r.aclose()


def test_store_never_issues_a_per_field_hash_ttl_command():
    """Redis 7.4 client method, Redis 7.2 server: this would fail at runtime, not at lint time."""
    banned = re.compile(r"\b(hexpire|hpexpire|hexpireat|hpexpireat|hpersist)\b", re.IGNORECASE)
    for path in (
        REPO_ROOT / "services" / "state_machine" / "store.py",
        REPO_ROOT / "shared" / "redis_keys.py",
    ):
        code = [
            line for line in path.read_text().splitlines() if not re.match(r"^\s*#", line)
        ]
        offenders = [line.strip() for line in code if banned.search(line)]
        assert offenders == [], f"{path.name}: {offenders}"
