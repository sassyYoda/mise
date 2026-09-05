"""
D-67a / research B-7: a soft ban is a FAILED poll in both non-success consumers.

`PollCompleted.status` gaining `"banned"` is only half the change. Two separate call sites —
`services/state_machine/consumer.py::_handle_completed` and
`scripts/replay_raw.py::_handle_completed` — each hard-coded the old `("error", "timeout")`
tuple, so widening the schema alone would have made every banned poll read as a HEALTHY one:
no UNKNOWN mark, the restaurant's last known slots left standing, and the fleet-wide blindness
POLL-06 exists to detect invisible to the state machine.

This file drives both functions directly, with a recording stub in place of the engine, and
asserts the SAME status matrix for each. It also pins the property that makes the fix durable:
the check is `!= "success"`, not membership in an allowlist, so a status the schema gains after
this commit is treated as a failure by consumers that have never heard of it — the safe
direction, since an unrecognised status is exactly when you least want to assume health.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import pytest

import scripts.replay_raw as replay
import services.state_machine.consumer as consumer_module
from services.state_machine.consumer import StateMachineConsumer
from shared.events import FAILED_POLL_STATUSES, PollCompleted

RID = 4242
T0 = 1_788_000_000_000
POLL_ID = UUID("11111111-2222-3333-4444-555555555555")

ALL_STATUSES = ("success", "error", "timeout", "banned")


class FuturePollCompleted(PollCompleted):
    """
    The schema as a LATER phase might widen it, with a status neither consumer knows about.

    Substituted for `PollCompleted` in each consumer module to prove the branch is `!=
    "success"` and not a membership test against `FAILED_POLL_STATUSES`. Without this, the
    "future status" property is untestable: the real Literal rejects an unknown status at the
    validation boundary, long before either branch runs.
    """

    status: Literal["success", "error", "timeout", "banned", "quarantined"]  # type: ignore[assignment]


class RecordingEngine:
    """Records mark_unknown calls. Nothing else about the engine matters here."""

    def __init__(self) -> None:
        self.marked: list[tuple[int, int]] = []

    async def mark_unknown(self, restaurant_id: int, polled_at_epoch_ms: int) -> None:
        self.marked.append((restaurant_id, polled_at_epoch_ms))


class StubConsumer:
    """A stand-in `self` for the unbound `_handle_completed`: no Kafka, no Redis, no Postgres."""

    def __init__(self, engine: RecordingEngine) -> None:
        self.engine = engine
        self.flushes = 0

    async def _flush(self) -> None:
        self.flushes += 1


class StubMessage:
    """The two attributes `_handle_completed` reads off an aiokafka record."""

    def __init__(self, value: bytes) -> None:
        self.value = value


def _completed(status: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "poll_id": str(POLL_ID),
        "source": "resy",
        "restaurant_id": RID,
        "polled_at_epoch_ms": T0,
        "status": status,
        "latency_ms": 1234,
    }
    payload.update(overrides)
    return payload


async def _run_consumer(status: str) -> RecordingEngine:
    engine = RecordingEngine()
    stub = StubConsumer(engine)
    msg = StubMessage(PollCompleted(**_completed(status)).to_bytes())
    await StateMachineConsumer._handle_completed(stub, msg)  # type: ignore[arg-type]
    return engine


async def _run_replay(status: str) -> RecordingEngine:
    engine = RecordingEngine()
    await replay._handle_completed(engine, _completed(status))  # type: ignore[arg-type]
    return engine


# --- the shared frozenset ----------------------------------------------------------------


def test_failed_poll_statuses_is_the_single_non_success_registry() -> None:
    assert FAILED_POLL_STATUSES == frozenset({"error", "timeout", "banned"})
    assert "success" not in FAILED_POLL_STATUSES
    assert "banned" in FAILED_POLL_STATUSES


# --- consumer ----------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["error", "timeout", "banned"])
async def test_consumer_marks_unknown_for_every_failed_status(status: str) -> None:
    engine = await _run_consumer(status)
    assert engine.marked == [(RID, T0)]


async def test_consumer_returns_early_for_success() -> None:
    """A success carries no new information here — availability.raw advances state (D-47)."""
    engine = await _run_consumer("success")
    assert engine.marked == []


async def test_consumer_flushes_the_unknown_mark_before_committing() -> None:
    """The mark has to reach Redis before the offset moves, or a crash loses it (D-46)."""
    engine = RecordingEngine()
    stub = StubConsumer(engine)
    msg = StubMessage(PollCompleted(**_completed("banned")).to_bytes())
    await StateMachineConsumer._handle_completed(stub, msg)  # type: ignore[arg-type]
    assert stub.flushes == 1


async def test_consumer_treats_an_unrecognised_future_status_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consumer_module, "PollCompleted", FuturePollCompleted)
    engine = RecordingEngine()
    stub = StubConsumer(engine)
    msg = StubMessage(FuturePollCompleted(**_completed("quarantined")).to_bytes())
    await StateMachineConsumer._handle_completed(stub, msg)  # type: ignore[arg-type]
    assert "quarantined" not in FAILED_POLL_STATUSES
    assert engine.marked == [(RID, T0)]


# --- replay script -----------------------------------------------------------------------


@pytest.mark.parametrize("status", ["error", "timeout", "banned"])
async def test_replay_marks_unknown_for_every_failed_status(status: str) -> None:
    engine = await _run_replay(status)
    assert engine.marked == [(RID, T0)]


async def test_replay_returns_early_for_success() -> None:
    engine = await _run_replay("success")
    assert engine.marked == []


async def test_replay_treats_an_unrecognised_future_status_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay, "PollCompleted", FuturePollCompleted)
    engine = RecordingEngine()
    await replay._handle_completed(engine, _completed("quarantined"))  # type: ignore[arg-type]
    assert engine.marked == [(RID, T0)]


# --- the two call sites may not diverge ---------------------------------------------------


@pytest.mark.parametrize("status", ALL_STATUSES)
async def test_both_consumers_agree_on_every_status(status: str) -> None:
    """
    The divergence guard. These two functions live in different files, are maintained by
    different concerns (a long-running service and an offline debugging CLI) and have already
    drifted apart once. If they ever disagree, a `banned` poll means one thing in production
    and another in replay — and replay is the tool you reach for to explain the incident.
    """
    assert (await _run_consumer(status)).marked == (await _run_replay(status)).marked
