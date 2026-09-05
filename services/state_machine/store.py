"""
StateStore implementations (D-40, D-42, D-49).

MemoryStateStore backs replay and unit tests. RedisStateStore is production. BufferedStateStore
is a write-behind wrapper that lets the consumer shell decide WHEN the engine's state writes
become durable, which is what makes the D-46 emit ordering (claim, send, record, persist,
commit) literally true even though the engine writes through its store while it diffs.

Every key string comes from `shared.redis_keys` and every redis-py cast lives there too, so
this module contains neither (D-42, research Pitfall 3).

TTL is KEY-level and refreshed on EVERY mutating call. Per-field hash TTL is a Redis 7.4
SERVER feature; the pinned server is redis:7.2-alpine and answers `ERR unknown command`, so
reaching for it would fail at runtime rather than at lint time (D-40, research Pitfall 6).
Named symbols: MemoryStateStore, RedisStateStore, BufferedStateStore
"""
from __future__ import annotations

import redis.asyncio as redis

from services.state_machine.engine import StateStore
from services.state_machine.models import MetaRecord, SlotRecord
from shared.redis_keys import (
    AVAIL_STATE_TTL_SECONDS,
    avail_meta_key,
    avail_state_key,
    hdel_slot_with_ttl,
    hgetall_slots,
    hset_meta_with_ttl,
    hset_slot_with_ttl,
)
from shared.telemetry import get_logger

log = get_logger(__name__)

# Field names inside the per-restaurant meta HASH (D-40).
META_UNKNOWN_SINCE = "unknown_since_ms"
META_LAST_SUCCESS = "last_success_ms"


def _text(value: object) -> str:
    """Decode defensively: `redis.from_url` defaults to `decode_responses=False`."""
    return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)


def _optional_int(value: str | None) -> int | None:
    """An absent field and an empty field both mean None; a corrupt one does too."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


class MemoryStateStore:
    """
    Dict-backed StateStore. Concrete implementations of the protocol:
    MemoryStateStore (P2, replay + unit tests), RedisStateStore (P2 plan 02-03, production).

    get_slots returns a copy so a caller may mutate state while iterating its own snapshot.
    """

    def __init__(self) -> None:
        self._slots: dict[tuple[int, str, int], dict[str, SlotRecord]] = {}
        self._meta: dict[int, MetaRecord] = {}

    async def get_slots(self, rid: int, date: str, party: int) -> dict[str, SlotRecord]:
        return dict(self._slots.get((rid, date, party), {}))

    async def put_slot(self, rid: int, date: str, party: int, key: str, rec: SlotRecord) -> None:
        self._slots.setdefault((rid, date, party), {})[key] = rec

    async def drop_slot(self, rid: int, date: str, party: int, key: str) -> None:
        bucket = self._slots.get((rid, date, party))
        if bucket is not None:
            bucket.pop(key, None)
            if not bucket:
                self._slots.pop((rid, date, party), None)

    async def get_meta(self, rid: int) -> MetaRecord:
        return self._meta.get(rid, MetaRecord())

    async def put_meta(self, rid: int, meta: MetaRecord) -> None:
        self._meta[rid] = meta

    def buckets(self) -> list[tuple[int, str, int]]:
        """Test/replay helper: every `(rid, date, party)` bucket holding at least one record."""
        return sorted(self._slots)


class RedisStateStore:
    """
    Production StateStore over one HASH per `(restaurant, date, party)` plus a meta HASH (D-40).

    Every mutating call refreshes the whole key's 25-hour TTL, which is the only expiry
    mechanism the pinned Redis 7.2 server offers — and it does so in the SAME transaction as
    the mutation. A HSET followed by a separate EXPIRE is the non-atomic shape this repo bans
    for SETNX+EXPIRE (Pitfall 7): dying between the two while the key is being created leaves a
    hash with no TTL that never expires, and it doubles the round trips on the hot path.
    Removing the last field of a HASH deletes the key naturally; an EXPIRE against an absent
    key is a no-op returning 0, so that case needs no special handling.
    """

    def __init__(self, client: redis.Redis) -> None:
        self.r = client

    async def get_slots(self, rid: int, date: str, party: int) -> dict[str, SlotRecord]:
        raw = await hgetall_slots(self.r, avail_state_key(rid, date, party))
        records: dict[str, SlotRecord] = {}
        for field, value in raw.items():
            name = _text(field)
            try:
                records[name] = SlotRecord.from_json(_text(value))
            except (ValueError, KeyError, TypeError, AttributeError):
                # An unreadable field is dropped rather than raised: the slot re-enters the
                # PENDING cycle and must be confirmed again, which is the safe direction.
                #
                # `AttributeError` is in the tuple because of CR-02 (iteration 3), and it is
                # not hypothetical: `UUID(x)` does NOT raise ValueError for a non-string, it
                # raises `AttributeError: 'int' object has no attribute 'replace'` from
                # `hex.replace(...)`. A stored `"e": 42` therefore escaped this except clause
                # entirely, left `get_slots`, left `DiffEngine.process()`, and landed in
                # `handle_message`'s transient arm — which since CR-01 (iteration 2) REWINDS
                # the partition and retries forever against a record that can never parse.
                # `from_json` now rejects a non-string `event_id` with a ValueError of its own,
                # so this widening is defence in depth: the catch here is deliberately by
                # CONSEQUENCE ("this field is unreadable"), not by the exception type today's
                # validator happens to raise, so a future validator cannot silently reopen the
                # hole. Anything broader (a bare `Exception`) would swallow a genuine bug in
                # the store itself, which is why it is a widened tuple and not `Exception`.
                log.warning("slot_record_unreadable", restaurant_id=rid, slot_key=name)
        return records

    async def put_slot(self, rid: int, date: str, party: int, key: str, rec: SlotRecord) -> None:
        await hset_slot_with_ttl(
            self.r, avail_state_key(rid, date, party), key, rec.to_json(), AVAIL_STATE_TTL_SECONDS
        )

    async def drop_slot(self, rid: int, date: str, party: int, key: str) -> None:
        await hdel_slot_with_ttl(
            self.r, avail_state_key(rid, date, party), key, AVAIL_STATE_TTL_SECONDS
        )

    async def get_meta(self, rid: int) -> MetaRecord:
        raw = await hgetall_slots(self.r, avail_meta_key(rid))
        if not raw:
            # An absent restaurant is healthy-but-unobserved, never an error (empty-input edge).
            return MetaRecord()
        fields = {_text(k): _text(v) for k, v in raw.items()}
        return MetaRecord(
            unknown_since_ms=_optional_int(fields.get(META_UNKNOWN_SINCE)),
            last_success_ms=_optional_int(fields.get(META_LAST_SUCCESS)),
        )

    async def put_meta(self, rid: int, meta: MetaRecord) -> None:
        # Both fields are always written, with "" standing in for None, so one HSET fully
        # replaces the record and a cleared UNKNOWN mark cannot linger.
        await hset_meta_with_ttl(
            self.r,
            avail_meta_key(rid),
            {
                META_UNKNOWN_SINCE: (
                    "" if meta.unknown_since_ms is None else str(meta.unknown_since_ms)
                ),
                META_LAST_SUCCESS: (
                    "" if meta.last_success_ms is None else str(meta.last_success_ms)
                ),
            },
            AVAIL_STATE_TTL_SECONDS,
        )


class BufferedStateStore:
    """
    Write-behind StateStore wrapper that hands the shell control of the state-write moment (D-46).

    The engine writes through its store as it diffs, so with a bare RedisStateStore a slot would
    be recorded AVAILABLE BEFORE the Kafka send. A crash in that window would leave a record the
    next diff reads as already-emitted, and the opening would be lost for good — the one outcome
    this phase exists to prevent. Buffering the writes and flushing them where D-46 puts the
    state write, after the broker has acked, makes the research Pattern 4 crash table true: a
    crash before the flush leaves the slot PENDING, and redelivery re-sends the same
    deterministic event id.

    Buffering alone is not enough, and that is what `flush_slot` is for. `DiffEngine.process()`
    runs to completion before any decision is applied, so by the time the shell emits the FIRST
    slot of a multi-slot poll, every OTHER slot's AVAILABLE record is already sitting in the
    buffer. A message-wide flush at that point makes all of them durable before their own Kafka
    send has happened — and a crash in that window leaves a later slot durably AVAILABLE with an
    event that was never sent, which the next diff reads as already-emitted. `flush_slot` makes
    exactly one slot durable, so a crash before a later slot's send leaves that slot PENDING and
    redelivery re-sends the same deterministic event id. The message-wide `flush` still runs at
    the tail of the message, for the writes no Emit covers (drops, closures, meta).

    Reads are the inner store overlaid with the pending writes, so the engine still sees its own
    writes and stays completely unaware of the buffering.
    """

    def __init__(self, inner: StateStore) -> None:
        self.inner = inner
        # value None means "this field was dropped", distinct from "no buffered write".
        self._slots: dict[tuple[int, str, int, str], SlotRecord | None] = {}
        self._meta: dict[int, MetaRecord] = {}

    async def get_slots(self, rid: int, date: str, party: int) -> dict[str, SlotRecord]:
        records = await self.inner.get_slots(rid, date, party)
        for (buf_rid, buf_date, buf_party, key), rec in self._slots.items():
            if (buf_rid, buf_date, buf_party) != (rid, date, party):
                continue
            if rec is None:
                records.pop(key, None)
            else:
                records[key] = rec
        return records

    async def put_slot(self, rid: int, date: str, party: int, key: str, rec: SlotRecord) -> None:
        self._slots[(rid, date, party, key)] = rec

    async def drop_slot(self, rid: int, date: str, party: int, key: str) -> None:
        self._slots[(rid, date, party, key)] = None

    async def get_meta(self, rid: int) -> MetaRecord:
        if rid in self._meta:
            return self._meta[rid]
        return await self.inner.get_meta(rid)

    async def put_meta(self, rid: int, meta: MetaRecord) -> None:
        self._meta[rid] = meta

    def pending(self) -> int:
        """How many writes are waiting to be flushed. Tests assert on it; the shell logs it."""
        return len(self._slots) + len(self._meta)

    def discard(self) -> None:
        """Throw away a failed message's partial writes rather than half-applying them."""
        self._slots.clear()
        self._meta.clear()

    async def flush_slot(self, rid: int, date: str, party: int, key: str) -> None:
        """
        Make ONE slot's buffered write durable, leaving every other buffered write pending.

        This is the D-46 step-3 state write, and it is deliberately narrower than `flush`: the
        record of a slot whose event has not been acked yet must NOT survive a crash. A slot
        with no buffered write is a no-op, not an error — the shell calls this unconditionally
        after a send, and a re-sent emit (the crashed-mid-emit branch) has nothing buffered.
        """
        slot = (rid, date, party, key)
        if slot not in self._slots:
            return
        rec = self._slots.pop(slot)
        if rec is None:
            await self.inner.drop_slot(rid, date, party, key)
        else:
            await self.inner.put_slot(rid, date, party, key, rec)

    async def flush(self) -> None:
        """Apply every buffered write to the durable store in a stable order, then clear."""
        for (rid, date, party, key), rec in sorted(self._slots.items()):
            if rec is None:
                await self.inner.drop_slot(rid, date, party, key)
            else:
                await self.inner.put_slot(rid, date, party, key, rec)
        for rid, meta in sorted(self._meta.items()):
            await self.inner.put_meta(rid, meta)
        self._slots.clear()
        self._meta.clear()
