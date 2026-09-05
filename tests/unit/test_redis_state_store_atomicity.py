"""Unit: WR-10 — HSET/HDEL + a separate EXPIRE is Pitfall 7 wearing a different hat.

``tests/unit/test_no_setnx_expire_pairs.py`` greps for ``.setnx(``, so it cannot see the same
non-atomic shape spelled as a mutation followed by a standalone ``EXPIRE``. Every mutating
call in ``RedisStateStore`` used to issue exactly that pair: if the process died (or the
connection dropped) between the two commands while the key was being CREATED, the hash was
left with no TTL and never expired — a permanently stale slot record that suppresses real
events. It also doubled the round trips on the hot path.

These tests drive the real store against a recording client, so the guard is behavioural
rather than textual.
"""
from __future__ import annotations

import pytest

from services.state_machine.models import MetaRecord, SlotRecord, SlotState
from services.state_machine.store import RedisStateStore
from shared.redis_keys import AVAIL_STATE_TTL_SECONDS


class _RecordingPipeline:
    def __init__(self, sink: list[list[tuple[str, tuple[object, ...]]]]) -> None:
        self._sink = sink
        self._queued: list[tuple[str, tuple[object, ...]]] = []

    async def __aenter__(self) -> _RecordingPipeline:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def hset(self, *args: object, **kwargs: object) -> _RecordingPipeline:
        self._queued.append(("hset", args))
        return self

    def hdel(self, *args: object, **kwargs: object) -> _RecordingPipeline:
        self._queued.append(("hdel", args))
        return self

    def expire(self, *args: object, **kwargs: object) -> _RecordingPipeline:
        self._queued.append(("expire", args))
        return self

    async def execute(self) -> list[int]:
        self._sink.append(list(self._queued))
        self._queued.clear()
        return [1, 1]


class _RecordingRedis:
    """Records transactions; a bare mutating command outside one is an error."""

    def __init__(self) -> None:
        self.transactions: list[list[tuple[str, tuple[object, ...]]]] = []
        self.bare_calls: list[str] = []

    def pipeline(self, transaction: bool = False) -> _RecordingPipeline:
        assert transaction is True, "the mutate+refresh pair must be a MULTI/EXEC transaction"
        return _RecordingPipeline(self.transactions)

    async def hset(self, *args: object, **kwargs: object) -> int:
        self.bare_calls.append("hset")
        return 1

    async def hdel(self, *args: object, **kwargs: object) -> int:
        self.bare_calls.append("hdel")
        return 1

    async def expire(self, *args: object, **kwargs: object) -> bool:
        self.bare_calls.append("expire")
        return True


def _record() -> SlotRecord:
    return SlotRecord(
        state=SlotState.PENDING,
        token="tok",
        first_seen_ms=1_800_000_000_000,
        first_poll_id="6f1b1c62-0000-4000-8000-000000000001",
        last_seen_ms=1_800_000_000_000,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda store: store.put_slot(42, "2026-05-01", 2, "19:00|bar", _record()),
        lambda store: store.drop_slot(42, "2026-05-01", 2, "19:00|bar"),
        lambda store: store.put_meta(42, MetaRecord(unknown_since_ms=1, last_success_ms=None)),
    ],
    ids=["put_slot", "drop_slot", "put_meta"],
)
async def test_every_mutation_refreshes_the_ttl_in_one_transaction(call) -> None:
    client = _RecordingRedis()
    store = RedisStateStore(client)  # type: ignore[arg-type]

    await call(store)

    assert client.bare_calls == [], (
        f"a mutating command ran outside the transaction: {client.bare_calls}"
    )
    assert len(client.transactions) == 1, "expected exactly one round trip"
    commands = [name for name, _args in client.transactions[0]]
    assert commands[-1] == "expire", f"the TTL refresh must be in the transaction: {commands}"
    assert len(commands) == 2, commands
    ttl_args = client.transactions[0][-1][1]
    assert ttl_args[-1] == AVAIL_STATE_TTL_SECONDS
