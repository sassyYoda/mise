"""Unit: CR-01 regression — two seating types sharing one booking token emit TWO events.

`parse_opentable` fans one timeslot out into one `Slot` per seating type (D-36: `seat_type`
is slot identity), and the shipped OpenTable fixture gives both of them the *same* `token`.
With a Layer-1 claim key of `event:{rid}:{date}:{party}:{token}` the second slot's `SET NX`
failed, its `Emit` was skipped rather than re-sent, and the opening was lost for good — while
`scripts/replay_raw.py`, which dedupes on `event_id` and uses no claim key at all, emitted
both. Same input, two different event streams: a direct STATE-06 violation.

These tests drive the REAL `StateMachineConsumer._handle_raw` over the UNMODIFIED fixture and
pin the three things that were wrong:

* two Kafka sends with two distinct `event_id`s,
* two `insert_event` calls (one analytics row per slot),
* replay produces the same two events, byte for byte, from the same input.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from scripts.replay_raw import replay
from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.store import BufferedStateStore, MemoryStateStore
from shared.events import AvailabilityEvent, AvailabilityRaw
from tests.unit.factories import make_raw

RID = 42
DATE = "2026-05-01"
PARTY = 2
T0 = 1_800_000_000_000
T1 = T0 + 9_000
CONFIRM_DELAY_MS = 8_000


class FakeRedis:
    """The two `set_nx_ex` behaviours that matter: True on a fresh key, None on a taken one."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


def _raw(polled_at_epoch_ms: int) -> AvailabilityRaw:
    """The shipped fixture, UNTRIMMED: seatingTypes ["bar", "standard"], one shared token."""
    return make_raw(
        rid=RID,
        dates=[DATE],
        parties=[PARTY],
        response=OPENTABLE_SUCCESS_RESPONSE,
        polled_at_epoch_ms=polled_at_epoch_ms,
    )


def _envelopes() -> list[dict[str, Any]]:
    return [
        {"topic": "availability.raw", "value": json.loads(_raw(t).to_bytes())}
        for t in (T0, T1)
    ]


def _shell(monkeypatch: pytest.MonkeyPatch) -> tuple[StateMachineConsumer, AsyncMock, AsyncMock]:
    durable = MemoryStateStore()
    buffer = BufferedStateStore(durable)
    producer = AsyncMock()
    inserted = AsyncMock()
    monkeypatch.setattr("services.state_machine.consumer.insert_event", inserted)
    shell = StateMachineConsumer(
        consumer=AsyncMock(),
        producer=producer,
        redis_client=FakeRedis(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=CONFIRM_DELAY_MS),
        store=durable,
        buffer=buffer,
    )
    return shell, producer, inserted


def _sent_events(producer: AsyncMock) -> list[AvailabilityEvent]:
    return [
        AvailabilityEvent.model_validate_json(call.kwargs["value"])
        for call in producer.send_and_wait.await_args_list
    ]


@pytest.mark.asyncio
async def test_the_fixture_really_carries_two_seating_types_and_one_token() -> None:
    """Guard the guard: if the fixture ever loses its second seating type, say so loudly."""
    timeslot = OPENTABLE_SUCCESS_RESPONSE["data"]["availability"][0]["availability"][0][
        "timeSlots"
    ][0]
    assert timeslot["seatingTypes"] == ["bar", "standard"]
    assert isinstance(timeslot["token"], str)


@pytest.mark.asyncio
async def test_two_seat_types_sharing_a_token_emit_two_events(monkeypatch) -> None:
    """The real `_handle_raw` path: two polls 9 s apart confirm BOTH slots."""
    shell, producer, inserted = _shell(monkeypatch)

    for polled_at in (T0, T1):
        await shell._handle_raw(SimpleNamespace(value=_raw(polled_at).to_bytes()))

    events = _sent_events(producer)
    assert len(events) == 2, f"expected one event per seating type, got {len(events)}"
    assert {e.seat_type for e in events} == {"bar", "standard"}
    assert len({e.event_id for e in events}) == 2, "the two events must carry distinct ids"
    assert len({e.booking_token for e in events}) == 1, "both slots share one booking token"
    assert inserted.await_count == 2, "one analytics row per confirmed slot (STATE-05)"


@pytest.mark.asyncio
async def test_each_slot_takes_its_own_layer_1_claim(monkeypatch) -> None:
    """Two distinct claim keys, so neither emission can suppress the other."""
    shell, _, _ = _shell(monkeypatch)
    redis_client: FakeRedis = shell.r  # type: ignore[assignment]

    for polled_at in (T0, T1):
        await shell._handle_raw(SimpleNamespace(value=_raw(polled_at).to_bytes()))

    claims = sorted(redis_client.keys)
    assert len(claims) == 2, f"expected one claim key per slot, got {claims}"
    assert all("19:00|" in key for key in claims), claims
    assert claims[0] != claims[1]


@pytest.mark.asyncio
async def test_production_and_replay_agree_byte_for_byte(monkeypatch) -> None:
    """STATE-06: the same raw input must produce the same event stream in both paths."""
    shell, producer, _ = _shell(monkeypatch)

    for polled_at in (T0, T1):
        await shell._handle_raw(SimpleNamespace(value=_raw(polled_at).to_bytes()))

    produced = [call.kwargs["value"] for call in producer.send_and_wait.await_args_list]
    replayed = [line.encode() for line in await replay(_envelopes(), CONFIRM_DELAY_MS)]

    assert len(replayed) == 2, f"replay must emit both slots too, got {len(replayed)}"
    assert sorted(produced) == sorted(replayed), "production and replay diverged on one input"
