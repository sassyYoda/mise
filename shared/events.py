"""
Pydantic v2 Kafka message schemas.
Single source of truth for all Kafka message contracts (D-06).
Named symbols: AvailabilityRaw, PollCompleted, AvailabilityEvent, NAMESPACE_MISE, make_event_id
"""
from __future__ import annotations

from typing import Any, Final, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

# Deterministic uuid5 namespace for every mise event id (D-54).
#
# NEVER CHANGE THIS VALUE. Every historical event_id in Kafka, in the
# availability_events hypertable, and in every committed golden replay file derives
# from it; changing it silently invalidates all of them and breaks byte-identical
# replay (STATE-06). It is a hard-coded literal on purpose — deriving it at import
# from a URL would let a future URL edit rewrite history.
NAMESPACE_MISE: Final[UUID] = UUID("629d45e6-9621-5f62-a1ea-dd826ede29f8")


def make_event_id(
    source: str,
    restaurant_id: int,
    date: str,
    party_size: int,
    slot_key: str,
    first_poll_id: str,
) -> UUID:
    """
    Build the deterministic event id for a slot-opened event (D-45).

    The canonical string is `{source}:{restaurant_id}:{date}:{party_size}:{slot_key}:{first_poll_id}`.
    Keying on the *first* poll id (not the confirming one) means a re-opened slot gets a
    genuinely new id while a redelivered confirmation reproduces the old one exactly.
    Both the recipe and the namespace are permanent; see NAMESPACE_MISE.

    KNOWN CONSTRAINT (WR-02, iteration 3) — THIS RECIPE IS NOT INJECTIVE, AND THE PREVIOUS
    WORDING HERE WAS WRONG. It claimed the ambiguity had to straddle `slot_key` and
    `first_poll_id` and was therefore blocked by the latter being a UUID. It does not, and it
    is not. `date`, `party_size` and `slot_key` are three ADJACENT components, all three are
    taken from the source response with nothing but an `isinstance` check
    (`date_entry.get("date")`, `_slot_party_size`, `time_slot`/`seatingTypes`), and none of
    them is escaped. A collision is therefore constructible from response data alone:

        make_event_id("opentable", 42, "2026-05-01",   2,  "19:00|bar", pid)
        make_event_id("opentable", 42, "2026-05-01:2", 19, "00|bar",    pid)
        -> the same uuid5

    `slot_key` is itself a lossy join (`f"{time_slot}|{seat_type or '-'}"`), so
    `("19:00|bar", None)` and `("19:00", "bar|-")` also collapse onto one id — see WR-01 in
    `.planning/deferred-items.md`, which records the reproduction and the escaping fix.
    `tests/unit/test_slot_key_collisions.py` pins both collisions so this constraint is
    executable rather than prose.

    The recipe is frozen NOT because the risk is bounded but because the output is permanent:
    every committed golden in `tests/fixtures/raw_streams/*.events.jsonl` and every
    `availability_events` row already encodes it. Any change must percent-escape EVERY
    component, regenerate the goldens, and carry a Redis-state cutover, all in one commit.
    The matching claim key in `shared.redis_keys.event_idempotency_key` already escapes its
    components; it could, because it is ephemeral (20-minute TTL) and appears in no golden.
    """
    return uuid5(NAMESPACE_MISE, f"{source}:{restaurant_id}:{date}:{party_size}:{slot_key}:{first_poll_id}")


class AvailabilityRaw(BaseModel):
    """Emitted to availability.raw for each completed OpenTable or Resy poll."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    polled_at_epoch_ms: int
    raw_response: dict[str, Any]
    request_params: dict[str, Any]

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


class PollCompleted(BaseModel):
    """Emitted to polls.completed after each poll attempt."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    polled_at_epoch_ms: int
    status: Literal["success", "error", "timeout"]
    latency_ms: int
    http_status: int | None = None
    error: str | None = None

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


class AvailabilityEvent(BaseModel):
    """
    Emitted to availability.events when a slot has been confirmed open by two
    independent successful polls at least confirm_delay_ms apart (D-45, STATE-04).

    restaurant_id is the PLATFORM id (OpenTable rid / Resy venue id), exactly as
    poll_log.restaurant_id already is (D-52). It is NOT the `restaurants` table primary
    key; the complete join key against `restaurants` is `(source, platform_id)`.

    The model carries no wall-clock field by design (D-45): produced_at_epoch_ms is the
    confirming poll's polled_at_epoch_ms, not `now`. That is what lets scripts/replay_raw.py
    regenerate a byte-identical stream from the raw topic alone (STATE-06).

    Field declaration order below IS the JSON wire order that byte-identical replay depends
    on — do not reorder. date and time_slot are plain strings, never datetime, so no timezone
    renderer can perturb the bytes.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    event_type: Literal["slot_opened"]
    source: Literal["opentable", "resy"]
    restaurant_id: int
    date: str
    time_slot: str
    party_size: int
    seat_type: str | None
    booking_token: str | None
    first_seen_at_epoch_ms: int
    confirmed_at_epoch_ms: int
    produced_at_epoch_ms: int
    confirming_poll_id: UUID

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")
