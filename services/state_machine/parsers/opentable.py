"""
OpenTable raw-payload normaliser (D-37, D-38a, D-39).

Shapes are [ASSUMED] per 01-RESEARCH.md section 4 — update from
services/poller/sources/opentable/README.md ## Query Shape after the
DevTools spike confirms the live response schema. Every walk below uses `.get()` chains and
explicit isinstance checks, never index assumption: one unhandled KeyError here would halt
the whole Kafka partition.

This module reads no clock and draws no entropy, so replay stays deterministic (D-49).
Named symbols: effective_coverage, parse_opentable
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.state_machine.models import ParsedPoll, Slot
from services.state_machine.parsers.errors import ParseError
from shared.events import AvailabilityRaw


def effective_coverage(request_params: Mapping[str, Any]) -> frozenset[tuple[str, int]]:
    """
    The `(date, party_size)` matrix this poll ACTUALLY observed (D-38a, research B-4).

    `request_params["party_sizes"]` declares `[2, 4]`, but the adapter issues a single call:
    services/poller/sources/opentable/graphql.py sends `"partySize": party_sizes[0]` and
    services/poller/sources/opentable/adapter.py does not loop. Using the declared list would
    make every party-4 slot "covered and absent" on every poll, closing them all falsely.

    Returns an empty set when either list is empty — an unbounded poll closes nothing.
    """
    # TODO(P3/POLL-02): widen to the full party_sizes list when the adapter loops party sizes.
    dates = request_params.get("dates") or []
    parties = request_params.get("party_sizes") or []
    if not isinstance(dates, list) or not isinstance(parties, list) or not dates or not parties:
        return frozenset()
    return frozenset((str(d), int(parties[0])) for d in dates)


def _seating_types(timeslot: Mapping[str, Any]) -> list[str | None]:
    """One slot per seating type; a payload without seating types yields a single untyped slot."""
    raw = timeslot.get("seatingTypes")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list) and raw:
        return [str(s) if s is not None else None for s in raw]
    return [None]


def _slot_party_size(timeslot: Mapping[str, Any], fallback: int) -> int:
    """
    Prefer a per-timeslot party size if the live payload ever carries one (research A2).

    The [ASSUMED] fixture has no such field, so today this always returns the effective
    party size the poll was issued with.
    """
    for field in ("partySize", "covers"):
        value = timeslot.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return fallback


def parse_opentable(raw: AvailabilityRaw) -> ParsedPoll:
    """
    Normalise one OpenTable `availability.raw` message into a ParsedPoll.

    Raises ParseError for a non-mapping payload, an empty payload, a GraphQL `errors` array,
    a missing `data` key, or a non-mapping `data`. A well-formed payload carrying zero slots
    is a VALID zero-slot observation, not an error (D-39).
    """
    payload = raw.raw_response
    if not isinstance(payload, Mapping):
        raise ParseError("payload not a mapping")
    if not payload:
        raise ParseError("empty payload")
    if payload.get("errors"):
        raise ParseError("graphql errors present")
    if "data" not in payload:
        raise ParseError("missing data key")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ParseError("data not a mapping")

    coverage = effective_coverage(raw.request_params)
    fallback_party = next(iter(sorted(p for _d, p in coverage)), None)

    slots: list[Slot] = []
    if fallback_party is not None:
        restaurants = data.get("availability")
        for restaurant in restaurants if isinstance(restaurants, list) else []:
            if not isinstance(restaurant, Mapping):
                continue
            rid = restaurant.get("restaurantId")
            if isinstance(rid, int) and rid != raw.restaurant_id:
                continue
            date_entries = restaurant.get("availability")
            for date_entry in date_entries if isinstance(date_entries, list) else []:
                if not isinstance(date_entry, Mapping):
                    continue
                date = date_entry.get("date")
                if not isinstance(date, str):
                    continue
                timeslots = date_entry.get("timeSlots")
                for timeslot in timeslots if isinstance(timeslots, list) else []:
                    if not isinstance(timeslot, Mapping):
                        continue
                    time_slot = timeslot.get("time")
                    if not isinstance(time_slot, str):
                        continue
                    token = timeslot.get("token")
                    party_size = _slot_party_size(timeslot, fallback_party)
                    for seat_type in _seating_types(timeslot):
                        slots.append(
                            Slot(
                                date=date,
                                party_size=party_size,
                                time_slot=time_slot,
                                seat_type=seat_type,
                                booking_token=str(token) if token is not None else None,
                            )
                        )

    return ParsedPoll(
        restaurant_id=raw.restaurant_id,
        source=raw.source,
        polled_at_epoch_ms=raw.polled_at_epoch_ms,
        poll_id=raw.poll_id,
        coverage=coverage,
        slots=tuple(slots),
    )
