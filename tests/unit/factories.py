"""
Deterministic builders for state-machine unit tests (D-45, D-49).
Every builder REQUIRES an explicit polled_at_epoch_ms and derives its poll id with uuid5,
so no unit test can depend on the wall clock, on randomness, or on a real 8-second wait.
Named symbols: make_raw, make_slot, make_parsed
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from services.state_machine.models import ParsedPoll, Slot

from shared.events import NAMESPACE_MISE, AvailabilityRaw


def deterministic_poll_id(source: str, rid: int, polled_at_epoch_ms: int) -> UUID:
    """Stable stand-in for the poller's uuid4 poll id, so repeated runs are byte-identical."""
    return uuid5(NAMESPACE_MISE, f"test-poll:{source}:{rid}:{polled_at_epoch_ms}")


def make_raw(
    *,
    rid: int,
    dates: list[str],
    parties: list[int],
    response: dict[str, Any],
    polled_at_epoch_ms: int,
    poll_id: UUID | None = None,
    source: str = "opentable",
) -> AvailabilityRaw:
    """Build an AvailabilityRaw exactly as services/poller/scheduler.py would publish it."""
    return AvailabilityRaw(
        poll_id=poll_id or deterministic_poll_id(source, rid, polled_at_epoch_ms),
        source=source,  # type: ignore[arg-type]
        restaurant_id=rid,
        polled_at_epoch_ms=polled_at_epoch_ms,
        raw_response=response,
        request_params={"rid": rid, "dates": list(dates), "party_sizes": list(parties)},
    )


def make_slot(
    *,
    date: str,
    party_size: int,
    time_slot: str,
    seat_type: str | None = None,
    booking_token: str | None = None,
) -> Slot:
    """Build a single parsed Slot without going through a parser."""
    return Slot(
        date=date,
        party_size=party_size,
        time_slot=time_slot,
        seat_type=seat_type,
        booking_token=booking_token,
    )


def make_parsed(
    *,
    rid: int,
    polled_at_epoch_ms: int,
    coverage: set[tuple[str, int]] | frozenset[tuple[str, int]],
    slots: list[Slot] | tuple[Slot, ...] = (),
    poll_id: UUID | None = None,
    source: str = "opentable",
) -> ParsedPoll:
    """Build a ParsedPoll directly, bypassing the parser, for transition-table tests."""
    return ParsedPoll(
        restaurant_id=rid,
        source=source,
        polled_at_epoch_ms=polled_at_epoch_ms,
        poll_id=poll_id or deterministic_poll_id(source, rid, polled_at_epoch_ms),
        coverage=frozenset(coverage),
        slots=tuple(slots),
    )
