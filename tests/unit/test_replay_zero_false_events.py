"""
ROADMAP Phase 2 SC1 in data form: a simulated transient-error stream produces ZERO events.

The single most damaging failure this pipeline can have is a false positive — waking someone
at 3 AM for a table that was never there. Every transient failure mode (timeout, 5xx, a
GraphQL errors array, an empty body) must flow to UNKNOWN and must never flip a slot to
UNAVAILABLE or promote a PENDING slot to AVAILABLE (D-39, D-41).

The companion flapping stream proves the other half: a slot seen, gone, and seen again is ONE
confirmed opening, not three.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.replay_raw import Envelope, read_envelopes, replay, run_input_mode
from shared.events import AvailabilityEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "raw_streams"

TRANSIENT_INPUT = FIXTURES / "transient_errors.jsonl"
TRANSIENT_GOLDEN = FIXTURES / "transient_errors.events.jsonl"
FLAPPING_INPUT = FIXTURES / "flapping.jsonl"
FLAPPING_GOLDEN = FIXTURES / "flapping.events.jsonl"

# The instant the flapping slot's SECOND cycle begins. The confirmed event must date from
# here, not from the first sighting 180 s earlier that was dropped unconfirmed.
FLAPPING_SECOND_SIGHTING_MS = 1788200180000


async def test_the_transient_error_stream_produces_zero_events() -> None:
    """SC1: not one false event from timeout, 503, GraphQL errors or an empty body."""
    assert await replay(read_envelopes(TRANSIENT_INPUT)) == []


async def test_the_transient_replay_matches_the_zero_byte_golden(tmp_path: Path) -> None:
    """
    The golden is compared as an artifact, not asserted as a count.

    A committed zero-byte file means a future regression that starts emitting shows up as a
    diff in review rather than as a changed integer inside a test.
    """
    out = tmp_path / "transient.events.jsonl"
    assert await run_input_mode(TRANSIENT_INPUT, out) == 0
    assert out.read_bytes() == b""
    assert TRANSIENT_GOLDEN.read_bytes() == b""
    assert out.read_bytes() == TRANSIENT_GOLDEN.read_bytes()


def test_the_stream_actually_carries_all_four_failure_modes() -> None:
    """
    Guard the guard: a zero-event assertion over a stream with no errors in it is vacuous.

    These four are the distinct transient failure shapes the poller can produce.
    """
    envelopes = read_envelopes(TRANSIENT_INPUT)
    completed = [e["value"] for e in envelopes if e["topic"] == "polls.completed"]
    raws = [e["value"] for e in envelopes if e["topic"] == "availability.raw"]

    assert any(c["status"] == "timeout" for c in completed)
    assert any(c["status"] == "error" and c.get("http_status") == 503 for c in completed)
    assert any(r["raw_response"].get("errors") for r in raws), "no GraphQL errors-array payload"
    assert any(r["raw_response"] == {} for r in raws), "no empty-payload poll"


async def test_a_pending_slot_is_never_promoted_by_an_error_burst() -> None:
    """
    The stream opens with a legitimate first sighting whose confirmation never arrives.

    Truncating the replay just before the recovery poll leaves that slot PENDING through four
    consecutive failures — and PENDING never emits.
    """
    envelopes = read_envelopes(TRANSIENT_INPUT)
    assert await replay(envelopes[:-1]) == []


async def test_the_final_clean_poll_drops_the_pending_slot_without_emitting() -> None:
    """
    D-41's false-positive guard: the recovery poll is a VALID zero-slot observation, so the
    unconfirmed ghost is dropped. A dropped slot produces no event and no close.
    """
    envelopes = read_envelopes(TRANSIENT_INPUT)
    recovery = envelopes[-1]
    assert recovery["topic"] == "availability.raw"
    assert recovery["value"]["raw_response"]["data"]["availability"][0]["availability"] == []
    assert await replay(envelopes) == []


async def test_the_transient_stream_is_order_independent() -> None:
    """
    D-53: UNKNOWN marking is monotonic in poll time, so delivery order cannot change the
    outcome. Two topics on one consumer are not delivered fairly (research Pitfall 2), so this
    property is what makes a replay reproducible regardless of how the broker interleaved them.
    """
    envelopes = read_envelopes(TRANSIENT_INPUT)
    raws: list[Envelope] = [e for e in envelopes if e["topic"] != "polls.completed"]
    completed: list[Envelope] = [e for e in envelopes if e["topic"] == "polls.completed"]
    assert completed, "reordering nothing would make this test vacuous"
    assert await replay(raws + completed) == []


async def test_the_flapping_stream_produces_exactly_one_event(tmp_path: Path) -> None:
    """
    Seen, gone, seen, confirmed. The first cycle is dropped unconfirmed; the second cycle is a
    genuinely new cycle with a new first_poll_id and therefore a new event_id — which is why
    the total is one event rather than three.
    """
    lines = await replay(read_envelopes(FLAPPING_INPUT))
    assert len(lines) == 1

    event = AvailabilityEvent.model_validate_json(lines[0])
    assert event.first_seen_at_epoch_ms == FLAPPING_SECOND_SIGHTING_MS
    assert event.confirmed_at_epoch_ms == FLAPPING_SECOND_SIGHTING_MS + 9000

    out = tmp_path / "flapping.events.jsonl"
    assert await run_input_mode(FLAPPING_INPUT, out) == 0
    assert out.read_bytes() == FLAPPING_GOLDEN.read_bytes()


def test_the_flapping_stream_really_flaps() -> None:
    """Guard the guard: the middle poll must genuinely omit the slot."""
    envelopes = read_envelopes(FLAPPING_INPUT)
    assert len(envelopes) == 4
    slot_counts = [
        len(e["value"]["raw_response"]["data"]["availability"][0]["availability"])
        for e in envelopes
    ]
    assert slot_counts == [1, 0, 1, 1]


def test_every_fixture_line_is_valid_json_and_a_tagged_envelope() -> None:
    """Both fixtures are hand-authored; a stray comma would otherwise fail somewhere confusing."""
    for fixture in (TRANSIENT_INPUT, FLAPPING_INPUT):
        for line in fixture.read_text().splitlines():
            if not line.strip():
                continue
            envelope = json.loads(line)
            assert set(envelope) == {"topic", "value"}
            assert envelope["topic"] in {"availability.raw", "polls.completed"}
