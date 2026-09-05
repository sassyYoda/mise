"""
In-memory StateStore for replay and unit tests (D-49).
No TTL semantics: expiry is a Redis concern and RedisStateStore arrives in plan 02-03.
Named symbols: MemoryStateStore
"""
from __future__ import annotations

from services.state_machine.models import MetaRecord, SlotRecord


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
