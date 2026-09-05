"""Unit: CR-02 regression — the state write is per-EMIT, never message-wide (D-46 step 3).

`DiffEngine.process()` runs to completion before the shell applies any decision, so by the
time the first `Emit` of a multi-slot poll is executed, every OTHER slot's AVAILABLE record is
already sitting in the `BufferedStateStore`. Flushing the whole buffer there made those records
durable BEFORE their own `send_and_wait`, and a SIGKILL in that window left a slot durably
AVAILABLE with an event that never reached Kafka: the next diff reads AVAILABLE, takes the
refresh path, and the opening is lost for good — verbatim the outcome `BufferedStateStore`
exists to prevent, and the outcome README rows 2 and 3 promise cannot happen.

Two tests, both driving the real `StateMachineConsumer`:

* the durable store is snapshotted at the exact moment of each Kafka send, and no slot may be
  AVAILABLE there before its own send has been acked;
* a simulated crash on the SECOND slot's send must leave that slot PENDING, so redelivery
  re-emits it.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.models import SlotState
from services.state_machine.store import BufferedStateStore, MemoryStateStore
from shared.events import AvailabilityEvent, AvailabilityRaw
from tests.unit.factories import make_raw

RID = 42
DATE = "2026-05-01"
PARTY = 2
T0 = 1_800_000_000_000
T1 = T0 + 9_000
CONFIRM_DELAY_MS = 8_000
BAR = "19:00|bar"
STANDARD = "19:00|standard"


class FakeRedis:
    """`set_nx_ex` semantics only: True on a fresh key, None on a taken one."""

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
    """The shipped fixture untrimmed: one timeslot, two seating types, two slots."""
    return make_raw(
        rid=RID,
        dates=[DATE],
        parties=[PARTY],
        response=OPENTABLE_SUCCESS_RESPONSE,
        polled_at_epoch_ms=polled_at_epoch_ms,
    )


def _msg(polled_at_epoch_ms: int) -> SimpleNamespace:
    return SimpleNamespace(
        topic="availability.raw",
        partition=0,
        offset=0,
        value=_raw(polled_at_epoch_ms).to_bytes(),
    )


def _shell(
    durable: MemoryStateStore,
    redis_client: FakeRedis,
    producer: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> StateMachineConsumer:
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    buffer = BufferedStateStore(durable)
    return StateMachineConsumer(
        consumer=AsyncMock(),
        producer=producer,
        redis_client=redis_client,  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=CONFIRM_DELAY_MS),
        store=durable,
        buffer=buffer,
    )


@pytest.mark.asyncio
async def test_no_slot_is_durably_available_before_its_own_send(monkeypatch) -> None:
    """Snapshot the durable store at each send: a later slot must still be PENDING."""
    durable = MemoryStateStore()
    producer = AsyncMock()
    snapshots: list[tuple[str, dict[str, SlotState]]] = []

    async def _capture(topic: str, *, value: bytes, key: str) -> None:
        event = AvailabilityEvent.model_validate_json(value)
        records = await durable.get_slots(RID, DATE, PARTY)
        snapshots.append(
            (
                f"{event.time_slot}|{event.seat_type}",
                {slot: rec.state for slot, rec in records.items()},
            )
        )

    producer.send_and_wait.side_effect = _capture
    shell = _shell(durable, FakeRedis(), producer, monkeypatch)

    for polled_at in (T0, T1):
        await shell._handle_raw(_msg(polled_at))

    assert [sent for sent, _ in snapshots] == [BAR, STANDARD], snapshots

    at_bar = dict(snapshots[0][1])
    assert at_bar.get(BAR) is not SlotState.AVAILABLE, "a slot is durable before its own send"
    assert at_bar.get(STANDARD) is SlotState.PENDING, (
        "the SECOND slot was made durably AVAILABLE before its Kafka send — a crash here "
        "loses that opening permanently (CR-02)"
    )

    at_standard = dict(snapshots[1][1])
    assert at_standard.get(BAR) is SlotState.AVAILABLE, "the acked slot must be durable by now"
    assert at_standard.get(STANDARD) is not SlotState.AVAILABLE

    final = await durable.get_slots(RID, DATE, PARTY)
    assert {k: v.state for k, v in final.items()} == {
        BAR: SlotState.AVAILABLE,
        STANDARD: SlotState.AVAILABLE,
    }


@pytest.mark.asyncio
async def test_a_crash_on_the_second_send_leaves_that_slot_pending_and_it_re_emits(
    monkeypatch,
) -> None:
    """The chaos window CR-02 opened: kill the process during slot 2's send, then redeliver."""
    durable = MemoryStateStore()
    redis_client = FakeRedis()

    crashing = AsyncMock()
    crashing.send_and_wait.side_effect = [None, RuntimeError("SIGKILL during the second send")]
    shell = _shell(durable, redis_client, crashing, monkeypatch)

    await shell._handle_raw(_msg(T0))
    # The confirming poll: slot 1 is sent and recorded, slot 2 dies mid-send.
    await shell.handle_message(_msg(T1))

    states = {k: v.state for k, v in (await durable.get_slots(RID, DATE, PARTY)).items()}
    assert states[BAR] is SlotState.AVAILABLE
    assert states[STANDARD] is SlotState.PENDING, (
        f"the un-sent slot must survive the crash as PENDING, got {states[STANDARD]}"
    )

    # Redelivery of the same uncommitted offset, on a clean shell over the same durable state.
    restarted_producer = AsyncMock()
    restarted = _shell(durable, redis_client, restarted_producer, monkeypatch)
    await restarted.handle_message(_msg(T1))

    resent = [
        AvailabilityEvent.model_validate_json(call.kwargs["value"])
        for call in restarted_producer.send_and_wait.await_args_list
    ]
    assert [e.seat_type for e in resent] == ["standard"], (
        "redelivery must re-send exactly the slot whose send never completed"
    )
    states = {k: v.state for k, v in (await durable.get_slots(RID, DATE, PARTY)).items()}
    assert states == {BAR: SlotState.AVAILABLE, STANDARD: SlotState.AVAILABLE}
