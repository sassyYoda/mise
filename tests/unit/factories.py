"""
Deterministic builders for state-machine unit tests (D-45, D-49).
Every builder REQUIRES an explicit polled_at_epoch_ms and derives its poll id with uuid5,
so no unit test can depend on the wall clock, on randomness, or on a real 8-second wait.
Named symbols: make_raw, make_slot, make_parsed, make_resy_envelope, make_resy_raw
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
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


def make_resy_envelope(
    *,
    dates: Sequence[str],
    party_sizes: Sequence[int],
    body: dict[str, Any] | None = None,
    bodies: Mapping[tuple[str, int], Any] | None = None,
    statuses: Mapping[tuple[str, int], int] | None = None,
    default_status: int = 200,
) -> dict[str, Any]:
    """
    Build the D-64 `availability.raw` envelope one Resy poll publishes.

    Shape: `{"requests": [{"date", "party_size", "status", "body"}, ...]}` — one entry per
    (date, party_size) pair the adapter actually issued, carrying the HTTP status that pair
    came back with. This is the whole point of D-64: `coverage` is derived from the entries
    that returned 200, so a rate-limited date can never be reported as "observed and empty"
    and close every real slot on it (the OpenTable B-4 defect, prevented for Resy from day
    one).

    Entries are emitted in ascending `(date, party_size)` order so two builds of the same
    inputs are byte-identical. Nothing here reads a clock or draws entropy (D-49).

    `bodies` and `statuses` override `body` / `default_status` for individual pairs, which is
    how the mixed-status matrix in `tests/unit/test_parsers_resy.py` is expressed without
    inlining a payload.
    """
    bodies = bodies or {}
    statuses = statuses or {}
    requests: list[dict[str, Any]] = []
    for date in sorted(dates):
        for party_size in sorted(party_sizes):
            pair = (date, party_size)
            requests.append(
                {
                    "date": date,
                    "party_size": party_size,
                    "status": statuses.get(pair, default_status),
                    "body": bodies.get(pair, body if body is not None else {}),
                }
            )
    return {"requests": requests}


def make_resy_raw(
    *,
    rid: int,
    dates: Sequence[str],
    parties: Sequence[int],
    polled_at_epoch_ms: int,
    body: dict[str, Any] | None = None,
    bodies: Mapping[tuple[str, int], Any] | None = None,
    statuses: Mapping[tuple[str, int], int] | None = None,
    default_status: int = 200,
    envelope: dict[str, Any] | None = None,
    poll_id: UUID | None = None,
) -> AvailabilityRaw:
    """
    An `AvailabilityRaw` with `source="resy"` whose `raw_response` is a D-64 envelope.

    `polled_at_epoch_ms` is REQUIRED, exactly as in `make_raw`: no Resy test may depend on the
    wall clock either. Pass `envelope=` to hand in a hand-built (or deliberately malformed)
    payload instead of one this factory generates.
    """
    payload = (
        envelope
        if envelope is not None
        else make_resy_envelope(
            dates=dates,
            party_sizes=parties,
            body=body,
            bodies=bodies,
            statuses=statuses,
            default_status=default_status,
        )
    )
    return make_raw(
        rid=rid,
        dates=list(dates),
        parties=list(parties),
        response=payload,
        polled_at_epoch_ms=polled_at_epoch_ms,
        poll_id=poll_id,
        source="resy",
    )
