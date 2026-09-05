"""
Value types shared by the parsers, the diff engine and the consumer shell (D-36, D-37, D-40, D-41).
Pure data only: this module performs no I/O, reads no clock and draws no entropy, so the
engine that imports it stays replay-deterministic (D-49).
Named symbols: SlotState, Slot, ParsedPoll, SlotRecord, MetaRecord, Expedite, Emit, Close,
Decision
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from shared.events import AvailabilityEvent

# The confirmation delay is NOT declared here. It used to be, as a second literal alongside
# shared.redis_keys.CONFIRM_DELAY_MS, to dodge an import edge that no longer conflicts — and
# the two agreed only by coincidence. Production read one and replay defaulted to the other,
# so changing either would have left every golden file and the byte-identity test asserting a
# confirmation window production no longer used. There is now exactly one:
# shared.redis_keys.CONFIRM_DELAY_MS (D-42, D-43).


class SlotState(StrEnum):
    """Per-slot lifecycle states (D-41). UNKNOWN is carried on the restaurant meta record."""

    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Slot:
    """One observed reservation slot. booking_token is data, not identity (D-36)."""

    date: str
    party_size: int
    time_slot: str
    seat_type: str | None
    booking_token: str | None

    @property
    def slot_key(self) -> str:
        """Redis hash field for this slot: `{time_slot}|{seat_type or '-'}` (D-36)."""
        return f"{self.time_slot}|{self.seat_type or '-'}"


@dataclass(frozen=True, slots=True)
class ParsedPoll:
    """A source-agnostic normalised poll. The diff engine never branches on source (D-37)."""

    restaurant_id: int
    source: str
    polled_at_epoch_ms: int
    poll_id: UUID
    coverage: frozenset[tuple[str, int]]
    slots: tuple[Slot, ...]


@dataclass(frozen=True, slots=True)
class SlotRecord:
    """
    Stored state for one slot (D-40). Serialised into a Redis hash field with stable compact
    keys `s,t,f,p,l,c,e`; the abbreviations are arbitrary but the round-trip must be exact.
    """

    state: SlotState
    token: str | None
    first_seen_ms: int
    first_poll_id: str
    last_seen_ms: int
    confirmed_ms: int | None = None
    event_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "s": self.state.value,
                "t": self.token,
                "f": self.first_seen_ms,
                "p": self.first_poll_id,
                "l": self.last_seen_ms,
                "c": self.confirmed_ms,
                "e": self.event_id,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> SlotRecord:
        raw = json.loads(payload)
        return cls(
            state=SlotState(raw["s"]),
            token=raw["t"],
            first_seen_ms=int(raw["f"]),
            first_poll_id=raw["p"],
            last_seen_ms=int(raw["l"]),
            confirmed_ms=None if raw["c"] is None else int(raw["c"]),
            event_id=raw["e"],
        )


@dataclass(frozen=True, slots=True)
class MetaRecord:
    """Restaurant-level poll health (D-40, D-53). Both fields are poll timestamps, never a clock read."""

    unknown_since_ms: int | None = None
    last_success_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Expedite:
    """Pull the restaurant's next poll forward so a PENDING slot can be confirmed (D-43)."""

    source: str
    restaurant_id: int


@dataclass(frozen=True, slots=True)
class Emit:
    """Publish a confirmed slot-opened event, claimed first with SET NX EX (D-46)."""

    event: AvailabilityEvent
    idempotency_token: str
    date: str
    party_size: int
    slot_key: str


@dataclass(frozen=True, slots=True)
class Close:
    """Close the DB row for a slot that vanished from a successful covered poll (D-41, D-48)."""

    event_id: UUID
    restaurant_id: int
    date: str
    party_size: int
    slot_key: str
    confirmed_at_epoch_ms: int
    last_seen_at_epoch_ms: int


Decision = Expedite | Emit | Close
