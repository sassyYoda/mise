"""
Resy raw-payload normaliser (D-64, D-66, D-39, D-49).

Shapes are `[ASSUMED]` per 03-RESEARCH.md §Assumptions Log A1/A2 — update from
services/poller/sources/resy/fixtures.py after the DevTools capture documented in
docs/runbooks/resy-cookie-capture.md confirms the live `/4/find` response schema. Every walk
below uses `.get()` chains and explicit isinstance checks, never index assumption: one
unhandled KeyError here would halt the whole Kafka partition (T-03-01).

COVERAGE COMES FROM THE ENVELOPE, NOT FROM `request_params`. `raw.raw_response` is the D-64
envelope `{"requests": [{"date", "party_size", "status", "body"}, ...]}` — one entry per
(date, party_size) pair the adapter actually issued, carrying the status that pair came back
with. `coverage` is exactly the pairs whose status is 200. This is the structural fix for the
defect class `parsers/opentable.py` still carries as a TODO: `request_params` DECLARES what a
poll intended to ask, and using it means a date that was rate-limited, or a party size the
adapter never looped over, is reported as "observed and empty" — which closes every real slot
on it (T-03-04, research B-4). A poll that never observed party 4 must never report party 4 as
covered.

An unusable body is a `ParseError`, which the consumer turns into UNKNOWN: it removes nothing
and closes nothing (D-39, D-41). A WELL-FORMED body carrying zero venues is the opposite — a
truthful zero-slot observation that closes covered slots, because a fully booked venue is
exactly what that looks like. At parse time an empty 200 is indistinguishable from a soft ban
serving an empty page (research Pitfall 10); telling those apart needs a rolling baseline this
module does not have and must not grow, so it is the POLL-06 canary's job, not the parser's.

`time_slot` is an `HH:MM` STRING SLICE of `slot.date.start`, never a parsed `datetime`, so no
timezone renderer can perturb the wire bytes that byte-identical replay depends on.

This module reads no clock and draws no entropy, so replay stays deterministic (D-49).
Named symbols: envelope_coverage, parse_resy
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from services.state_machine.models import ParsedPoll, Slot
from services.state_machine.parsers.errors import ParseError
from shared.events import AvailabilityRaw
from shared.telemetry import get_logger

log = get_logger(__name__)

# The one status that means "this pair was actually observed". Anything else — 429, 403, 500,
# a Cloudflare interstitial — is an attempt, not an observation.
_OBSERVED_STATUS: int = 200

# `HH:MM`, and nothing else. A slice that does not match this is not a time and the slot it
# came from is dropped rather than turned into a slot_key nothing will ever match again.
_HH_MM = re.compile(r"^\d{2}:\d{2}$")


def _entry_pair(entry: Mapping[str, Any]) -> tuple[str, int] | None:
    """
    The `(date, party_size)` this envelope entry observed, or None if it is unusable.

    Returns None rather than raising, and the caller then contributes NO coverage for it. That
    is the safe direction: an entry whose metadata cannot be read closes nothing on that date,
    while the rest of the poll still lands. If it turns out that EVERY entry is unusable,
    `parse_resy` raises — a poll that observed nothing is UNKNOWN, not an observation of
    nothing.
    """
    date = entry.get("date")
    party_size = entry.get("party_size")
    if not isinstance(date, str) or not date:
        return None
    # `isinstance(True, int)` is True in Python, and `("2026-05-01", True)` would be a coverage
    # bucket no stored slot can ever match.
    if not isinstance(party_size, int) or isinstance(party_size, bool):
        return None
    return (date, party_size)


def _is_observed(entry: Mapping[str, Any]) -> bool:
    """True only for a status that is literally the integer 200 (booleans excluded)."""
    status = entry.get("status")
    return isinstance(status, int) and not isinstance(status, bool) and status == _OBSERVED_STATUS


def _venues(entry: Mapping[str, Any]) -> list[Any]:
    """
    The `results.venues` list of one OBSERVED entry, or `ParseError`.

    This is the poll-level unusability boundary, and every check here is the difference between
    two outcomes that are NOT close: an unreadable body is UNKNOWN and closes nothing, while a
    readable body with no availability closes every slot in coverage. Guessing wrong in the
    second direction wipes a restaurant's entire slot state on the strength of a response
    nobody has verified.

    `venues` must be a LIST specifically. `venues: []` is a real observation — a fully booked
    venue — but `results` carrying no `venues` key at all, or a `venues` of some other type, is
    a shape this parser has never seen. The `[ASSUMED]` schema (research A1) is exactly the
    kind of thing that turns out to be wrong in production, so the unrecognised case takes the
    recoverable path.
    """
    body = entry.get("body")
    if not isinstance(body, Mapping):
        raise ParseError(f"envelope entry body is not a mapping (got {type(body).__name__})")
    if "results" not in body:
        raise ParseError("envelope entry body has no results key")
    results = body.get("results")
    if not isinstance(results, Mapping):
        raise ParseError(f"results is not a mapping (got {type(results).__name__})")
    venues = results.get("venues")
    if not isinstance(venues, list):
        raise ParseError(f"results.venues is not a list (got {type(venues).__name__})")
    return venues


def envelope_coverage(payload: Any) -> tuple[frozenset[tuple[str, int]], list[Mapping[str, Any]]]:
    """
    Validate the D-64 envelope and return `(coverage, observed_entries)`.

    Raises ParseError for a non-mapping payload, a missing or non-list `requests`, an empty
    `requests`, and an envelope in which no entry returned 200 — that last one is the important
    case: a poll where every date was rate-limited or challenged observed NOTHING, and
    reporting it as a successful poll with empty coverage would let the caller mark the
    restaurant healthy while it is in fact blind.

    Entry order is preserved exactly as the adapter emitted it, which is what makes two parses
    of one envelope produce byte-identical slot tuples.
    """
    if not isinstance(payload, Mapping):
        raise ParseError(f"payload not a mapping (got {type(payload).__name__})")
    requests = payload.get("requests")
    if "requests" not in payload or not isinstance(requests, list):
        raise ParseError("envelope has no requests list")
    if not requests:
        raise ParseError("envelope requests list is empty: the poll issued no requests")

    pairs: list[tuple[str, int]] = []
    observed: list[Mapping[str, Any]] = []
    for entry in requests:
        if not isinstance(entry, Mapping):
            continue
        # THE D-64 COVERAGE RULE, and the whole reason the envelope exists. A non-200 entry is
        # skipped before its body is ever looked at, so a rate-limited or challenged date
        # contributes no coverage and therefore closes no slots on that date (T-03-04).
        if not _is_observed(entry):
            continue
        pair = _entry_pair(entry)
        if pair is None:
            continue
        pairs.append(pair)
        observed.append(entry)

    if not observed:
        raise ParseError(
            "no envelope entry returned 200: a poll that observed nothing cannot be "
            "reported as a successful observation"
        )
    return frozenset(pairs), observed


def _time_slot(start: Any) -> str | None:
    """
    `HH:MM` of `slot.date.start`, as a pure string slice (D-66).

    `[ASSUMED]` shape is `"YYYY-MM-DD HH:MM:SS"`; an ISO `T` separator and a bare `"HH:MM:SS"`
    are both accepted because the capture that would settle it has not happened yet. Nothing
    here constructs a `datetime`: a parsed-and-reformatted time would make the emitted wire
    bytes depend on the process timezone, and every golden replay file would drift with it.
    """
    if not isinstance(start, str):
        return None
    tail = start.replace("T", " ").split(" ")[-1]
    candidate = tail[:5]
    return candidate if _HH_MM.match(candidate) else None


def _booking_token(config: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """
    `(token, source_field)` — `config.token`, falling back to `config.id` (D-66, research A2).

    Public captures disagree about which field carries the bookable handle, so the parser
    accepts both and reports WHICH ONE it used. Only the field NAME ever leaves this function:
    the value is a third-party reservation handle and must never reach a log line (T-03-03).
    """
    for field in ("token", "id"):
        value = config.get(field)
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        return str(value), field
    return None, None


def parse_resy(raw: AvailabilityRaw) -> ParsedPoll:
    """
    Normalise one Resy `availability.raw` message into a ParsedPoll.

    Raises ParseError for a non-mapping payload, a missing/non-list/empty `requests`, an
    envelope with zero 200 entries, and a 200 entry whose body is unreadable (not a mapping, no
    `results`, or a non-mapping `results`). Every OTHER defect is per-slot and is skipped with
    `continue`: one malformed slot must not blind the whole restaurant, and raising on it would
    convert a partial reading into a total blackout.

    Slots take their `date` and `party_size` from the ENVELOPE ENTRY that produced them, not
    from the slot body. That keeps every emitted slot inside a `(date, party_size)` bucket that
    is also in `coverage` — a slot in a bucket the poll did not cover would be opened and then
    never closed, because closure is bounded by coverage (D-38a).
    """
    coverage, observed = envelope_coverage(raw.raw_response)

    slots: list[Slot] = []
    token_fields: set[str] = set()
    skipped = 0
    for entry in observed:
        pair = _entry_pair(entry)
        if pair is None:  # pragma: no cover - envelope_coverage already filtered these out
            continue
        date, party_size = pair
        for venue in _venues(entry):
            if not isinstance(venue, Mapping):
                skipped += 1
                continue
            venue_slots = venue.get("slots")
            for slot in venue_slots if isinstance(venue_slots, list) else []:
                if not isinstance(slot, Mapping):
                    skipped += 1
                    continue
                slot_date = slot.get("date")
                if not isinstance(slot_date, Mapping):
                    skipped += 1
                    continue
                time_slot = _time_slot(slot_date.get("start"))
                if time_slot is None:
                    skipped += 1
                    continue
                config = slot.get("config")
                if not isinstance(config, Mapping):
                    skipped += 1
                    continue
                # `size` is a SHAPE guard only. Filtering on size.min/max would silently drop
                # slots the poll genuinely saw, and a dropped slot in a covered bucket is
                # closed — deliberately not done here.
                size = slot.get("size")
                if size is not None and not isinstance(size, Mapping):
                    skipped += 1
                    continue
                seat_type = config.get("type")
                token, token_field = _booking_token(config)
                if token_field is not None:
                    token_fields.add(token_field)
                slots.append(
                    Slot(
                        date=date,
                        party_size=party_size,
                        time_slot=time_slot,
                        seat_type=seat_type if isinstance(seat_type, str) else None,
                        booking_token=token,
                    )
                )

    # One line per poll, and it names FIELDS and COUNTS only — never a booking token, never a
    # payload body (T-03-03). `token_fields` is what will tell the A2 assumption apart from
    # reality once real traffic flows: a production stream that only ever shows {"id"} means
    # `config.token` does not exist and Phase 4's deep link is degraded everywhere.
    log.debug(
        "resy_poll_parsed",
        restaurant_id=raw.restaurant_id,
        poll_id=str(raw.poll_id),
        covered_pairs=len(coverage),
        slots=len(slots),
        slots_skipped=skipped,
        booking_token_fields=sorted(token_fields),
    )

    return ParsedPoll(
        restaurant_id=raw.restaurant_id,
        source=raw.source,
        polled_at_epoch_ms=raw.polled_at_epoch_ms,
        poll_id=raw.poll_id,
        coverage=coverage,
        slots=tuple(slots),
    )
