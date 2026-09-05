"""
Tracer: two raw Resy polls 9000 ms apart become AvailabilityEvents through the UNCHANGED engine.

This is the SC5 proof at the unit tier. Phase 3's riskiest architectural claim is that Resy is
a second *source*, not a second *pipeline* — that the Phase-2 `DiffEngine` needs no
source-specific branch to diff it. The file therefore does two jobs:

  1. Walks a D-64 Resy envelope from `AvailabilityRaw` to `AvailabilityEvent` with exactly the
     control flow `tests/unit/test_tracer_raw_to_event.py` walks for OpenTable — first poll
     expedites and emits nothing, confirming poll emits and expedites nothing.
  2. Reads `services/state_machine/engine.py` off disk and asserts it names no source platform,
     so the claim cannot decay into a `if source == "resy"` that the behavioural tests above
     would happily keep passing.

Runs entirely in-process — no Redis, no Kafka, no Postgres, no network, no wall clock
(D-49, D-64, D-66, D-67a; POLL-05, POLL-06).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from services.state_machine.parsers.resy import parse_resy

from services.poller.sources.resy.fixtures import (
    RESY_DUPLICATE_SLOT_RESPONSE,
    RESY_FIXTURE_VENUE_ID,
    RESY_SUCCESS_RESPONSE,
)
from services.state_machine.engine import DiffEngine
from services.state_machine.models import Emit, Expedite
from services.state_machine.parsers import PARSER_REGISTRY, parse_raw
from services.state_machine.store import MemoryStateStore
from shared.events import AvailabilityEvent, AvailabilityRaw
from tests.unit.factories import make_resy_raw

RID = RESY_FIXTURE_VENUE_ID
DATE = "2026-05-01"
PARTY = 2
FIRST_POLL_MS = 1_788_000_000_000
CONFIRM_POLL_MS = 1_788_000_009_000  # 9000 ms later, above the 8000 ms confirm delay
CONFIRM_DELAY_MS = 8_000

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = REPO_ROOT / "services" / "state_machine" / "engine.py"

_FULL_LINE_COMMENT = re.compile(r"^\s*#")


def _raw(polled_at_epoch_ms: int, body: dict[str, Any] | None = None) -> AvailabilityRaw:
    return make_resy_raw(
        rid=RID,
        dates=[DATE],
        parties=[PARTY],
        body=RESY_SUCCESS_RESPONSE if body is None else body,
        polled_at_epoch_ms=polled_at_epoch_ms,
    )


async def _run_two_polls() -> tuple[list[object], list[object]]:
    engine = DiffEngine(MemoryStateStore(), confirm_delay_ms=CONFIRM_DELAY_MS)
    first = await engine.process(parse_raw(_raw(FIRST_POLL_MS)))
    second = await engine.process(parse_raw(_raw(CONFIRM_POLL_MS)))
    return list(first), list(second)


def _event(decisions: list[object], seat_type: str) -> AvailabilityEvent:
    emits = [d for d in decisions if isinstance(d, Emit)]
    matching = [e for e in emits if e.event.seat_type == seat_type]
    assert len(matching) == 1, seat_type
    return matching[0].event


async def test_first_poll_expedites_and_emits_nothing() -> None:
    """A first sighting yields exactly one Expedite (one per restaurant) and zero events."""
    first, _second = await _run_two_polls()
    assert [d for d in first if isinstance(d, Expedite)] == [Expedite(source="resy", restaurant_id=RID)]
    assert [d for d in first if isinstance(d, Emit)] == []


async def test_second_poll_confirms_and_emits_without_expediting() -> None:
    """The confirming poll emits one event per observed slot and expedites nothing further."""
    _first, second = await _run_two_polls()
    assert [d for d in second if isinstance(d, Expedite)] == []
    emits = [d for d in second if isinstance(d, Emit)]
    # RESY_SUCCESS_RESPONSE carries three slots across three config.type values.
    assert len(emits) == 3
    assert [e.event.seat_type for e in emits] == ["Bar", "Dining Room", "Patio"]  # sorted by slot_key


async def test_confirmed_event_field_values_come_from_the_payload() -> None:
    """Every field of the confirmed event comes from the Resy payload, never the clock (D-66)."""
    _first, second = await _run_two_polls()
    event = _event(second, "Dining Room")
    assert event.event_type == "slot_opened"
    assert event.source == "resy"
    assert event.restaurant_id == RID
    assert event.date == DATE
    # HH:MM of `slot.date.start` ("2026-05-01 19:00:00"), taken as a string slice: no datetime
    # is ever constructed, so no timezone renderer can perturb the wire bytes.
    assert event.time_slot == "19:00"
    assert event.party_size == PARTY
    assert event.seat_type == "Dining Room"
    assert event.booking_token == "rgs-dining-room-1900"
    assert event.first_seen_at_epoch_ms == FIRST_POLL_MS
    assert event.confirmed_at_epoch_ms == CONFIRM_POLL_MS
    assert event.produced_at_epoch_ms == CONFIRM_POLL_MS
    assert event.confirming_poll_id == _raw(CONFIRM_POLL_MS).poll_id


async def test_booking_token_falls_back_to_config_id() -> None:
    """A2: public captures show both `config.token` and `config.id`; the fallback is exercised."""
    _first, second = await _run_two_polls()
    patio = _event(second, "Patio")
    assert patio.time_slot == "21:30"
    assert patio.booking_token == "333"


async def test_replaying_the_same_polls_is_byte_identical() -> None:
    """A fresh MemoryStateStore replaying the same two messages reproduces the same bytes."""
    _first_a, second_a = await _run_two_polls()
    _first_b, second_b = await _run_two_polls()
    for seat_type in ("Bar", "Dining Room", "Patio"):
        event_a = _event(second_a, seat_type)
        event_b = _event(second_b, seat_type)
        assert event_a.event_id == event_b.event_id
        assert event_a.to_bytes() == event_b.to_bytes()


def test_parse_resy_is_order_stable() -> None:
    """Two parses of ONE envelope agree on coverage and produce byte-identical slot tuples."""
    raw = _raw(FIRST_POLL_MS)
    first = parse_resy(raw)
    second = parse_resy(raw)
    assert first.coverage == second.coverage == frozenset({(DATE, PARTY)})
    assert first.slots == second.slots
    assert [s.slot_key for s in first.slots] == [
        "19:00|Dining Room",
        "19:00|Bar",
        "21:30|Patio",
    ]


async def test_colliding_slots_are_counted_not_silently_dropped() -> None:
    """
    Two slots that collapse onto one `slot_key` resolve last-parsed-wins AND are counted (D-36).

    The parser emits both; `DiffEngine.last_collision_count` is what makes the collapse visible
    to the consumer's audit log instead of a silent single-field overwrite.
    """
    raw = _raw(FIRST_POLL_MS, RESY_DUPLICATE_SLOT_RESPONSE)
    parsed = parse_resy(raw)
    assert len(parsed.slots) == 2
    assert {s.slot_key for s in parsed.slots} == {"20:00|Bar"}

    engine = DiffEngine(MemoryStateStore(), confirm_delay_ms=CONFIRM_DELAY_MS)
    await engine.process(parsed)
    assert engine.last_collision_count == 1


def _engine_code_lines() -> list[tuple[int, str]]:
    """Engine source with full-line comments stripped, so prose cannot satisfy or break a gate."""
    return [
        (lineno, line)
        for lineno, line in enumerate(ENGINE_PATH.read_text().splitlines(), start=1)
        if not _FULL_LINE_COMMENT.match(line)
    ]


def test_engine_source_scan_is_not_vacuous() -> None:
    """A scan of an empty or moved file would make the two assertions below prove nothing."""
    assert ENGINE_PATH.is_file(), ENGINE_PATH
    lines = _engine_code_lines()
    assert len(lines) >= 100
    assert any("class DiffEngine" in line for _lineno, line in lines)


def test_the_diff_engine_names_no_source_platform() -> None:
    """
    SC5: adding Resy added a parser, not a branch (D-66, D-67a; research B-7).

    The check is for a source-key STRING LITERAL, which is what a source branch is actually
    made of — `if parsed.source == "resy"`. Prose in a docstring naming a platform is not a
    branch and is not what SC5 forbids.
    """
    lines = _engine_code_lines()
    offenders = [
        f"engine.py:{lineno}: {line.strip()}"
        for lineno, line in lines
        for key in PARSER_REGISTRY
        if f'"{key}"' in line or f"'{key}'" in line
    ]
    assert offenders == [], (
        "the diff engine must never branch on a source platform (SC5): " f"{offenders}"
    )
    # B-7 restates the criterion for the source THIS plan adds: no occurrence at all, in any
    # casing, anywhere in the engine's code.
    resy_mentions = [
        f"engine.py:{lineno}: {line.strip()}"
        for lineno, line in lines
        if "resy" in line.lower()
    ]
    assert resy_mentions == []


def test_parser_registry_holds_exactly_the_two_supported_sources() -> None:
    """Resy is one dict entry. A third key here means someone added a pipeline, not a parser."""
    assert sorted(PARSER_REGISTRY) == ["opentable", "resy"]
    assert PARSER_REGISTRY["resy"] is parse_resy
