"""
Pure diff engine: normalised poll in, decisions out (D-41, D-44, D-49; STATE-02, STATE-04).

Functional core / imperative shell. This module performs no I/O of any kind, reads no clock and
draws no entropy — every timestamp in every decision comes from the message's polled_at_epoch_ms,
and all state access goes through the StateStore protocol. That is precisely what makes
byte-identical replay provable in CI (STATE-06); a single clock read here would make it flake.
Named symbols: StateStore, DiffEngine
"""
from __future__ import annotations

from typing import Protocol

from services.state_machine.models import (
    Close,
    Decision,
    Emit,
    Expedite,
    MetaRecord,
    ParsedPoll,
    Slot,
    SlotRecord,
    SlotState,
)
from shared.events import AvailabilityEvent, make_event_id


class StateStore(Protocol):
    """
    Slot/meta persistence seam (D-49). Concrete implementations:
    MemoryStateStore (P2, replay + unit tests), RedisStateStore (P2 plan 02-03, production).
    """

    async def get_slots(self, rid: int, date: str, party: int) -> dict[str, SlotRecord]: ...

    async def put_slot(self, rid: int, date: str, party: int, key: str, rec: SlotRecord) -> None: ...

    async def drop_slot(self, rid: int, date: str, party: int, key: str) -> None: ...

    async def get_meta(self, rid: int) -> MetaRecord: ...

    async def put_meta(self, rid: int, meta: MetaRecord) -> None: ...


def _sort_key(decision: Decision) -> tuple[str, int, str, int]:
    """
    Total, stable order over decisions: `(date, party_size, slot_key)` with a kind tiebreak.

    Expedite carries no slot coordinates, so it sorts first with a sentinel; that keeps the
    returned list fully specified and reproducible across runs, which replay line order needs.
    """
    if isinstance(decision, Expedite):
        return ("", -1, "", 0)
    if isinstance(decision, Close):
        return (decision.date, decision.party_size, decision.slot_key, 1)
    return (decision.date, decision.party_size, decision.slot_key, 2)


class DiffEngine:
    """
    Tri-state slot diff (D-41). confirm_delay_ms is a REQUIRED argument: the engine imports no
    timing constant from a module another plan may be editing, and tests state it explicitly.
    """

    def __init__(self, store: StateStore, confirm_delay_ms: int) -> None:
        self.store = store
        self.confirm_delay_ms = confirm_delay_ms

    async def process(self, parsed: ParsedPoll) -> list[Decision]:
        """Diff one normalised poll against stored state and return the decisions to execute."""
        decisions: list[Decision] = []
        seen = _group_by_bucket(parsed.slots)
        needs_expedite = False

        for (date, party), observed in sorted(seen.items()):
            records = await self.store.get_slots(parsed.restaurant_id, date, party)
            for key, slot in sorted(observed.items()):
                record = records.get(key)
                if record is None:
                    await self._open_cycle(parsed, slot, key)
                    needs_expedite = True
                elif record.state is SlotState.PENDING:
                    emit = await self._confirm_or_wait(parsed, slot, key, record)
                    if emit is None:
                        needs_expedite = True
                    else:
                        decisions.append(emit)

        if needs_expedite:
            decisions.append(Expedite(source=parsed.source, restaurant_id=parsed.restaurant_id))
        return sorted(decisions, key=_sort_key)

    async def _open_cycle(self, parsed: ParsedPoll, slot: Slot, key: str) -> None:
        """First sighting: store PENDING and let the caller pull the next poll forward (D-41)."""
        await self.store.put_slot(
            parsed.restaurant_id,
            slot.date,
            slot.party_size,
            key,
            SlotRecord(
                state=SlotState.PENDING,
                token=slot.booking_token,
                first_seen_ms=parsed.polled_at_epoch_ms,
                first_poll_id=str(parsed.poll_id),
                last_seen_ms=parsed.polled_at_epoch_ms,
            ),
        )

    async def _confirm_or_wait(
        self,
        parsed: ParsedPoll,
        slot: Slot,
        key: str,
        record: SlotRecord,
    ) -> Emit | None:
        """PENDING seen again: confirm past confirm_delay_ms, otherwise keep waiting (D-44)."""
        elapsed = parsed.polled_at_epoch_ms - record.first_seen_ms
        if elapsed < self.confirm_delay_ms:
            await self.store.put_slot(
                parsed.restaurant_id,
                slot.date,
                slot.party_size,
                key,
                SlotRecord(
                    state=SlotState.PENDING,
                    token=slot.booking_token,
                    first_seen_ms=record.first_seen_ms,
                    first_poll_id=record.first_poll_id,
                    last_seen_ms=parsed.polled_at_epoch_ms,
                ),
            )
            return None

        event = AvailabilityEvent(
            event_id=make_event_id(
                parsed.source,
                parsed.restaurant_id,
                slot.date,
                slot.party_size,
                key,
                record.first_poll_id,
            ),
            event_type="slot_opened",
            source=parsed.source,  # type: ignore[arg-type]
            restaurant_id=parsed.restaurant_id,
            date=slot.date,
            time_slot=slot.time_slot,
            party_size=slot.party_size,
            seat_type=slot.seat_type,
            booking_token=slot.booking_token,
            first_seen_at_epoch_ms=record.first_seen_ms,
            confirmed_at_epoch_ms=parsed.polled_at_epoch_ms,
            produced_at_epoch_ms=parsed.polled_at_epoch_ms,
            confirming_poll_id=parsed.poll_id,
        )
        await self.store.put_slot(
            parsed.restaurant_id,
            slot.date,
            slot.party_size,
            key,
            SlotRecord(
                state=SlotState.AVAILABLE,
                token=slot.booking_token,
                first_seen_ms=record.first_seen_ms,
                first_poll_id=record.first_poll_id,
                last_seen_ms=parsed.polled_at_epoch_ms,
                confirmed_ms=parsed.polled_at_epoch_ms,
                event_id=str(event.event_id),
            ),
        )
        return Emit(
            event=event,
            idempotency_token=slot.booking_token or key,
            date=slot.date,
            party_size=slot.party_size,
            slot_key=key,
        )


def _group_by_bucket(slots: tuple[Slot, ...]) -> dict[tuple[str, int], dict[str, Slot]]:
    """
    Group observed slots by `(date, party_size)` then by slot_key.

    Two slots in one poll with an identical `(time_slot, seat_type)` collapse to one field,
    last parsed winning — a deterministic, specified resolution of the adjacency case.
    """
    grouped: dict[tuple[str, int], dict[str, Slot]] = {}
    for slot in slots:
        grouped.setdefault((slot.date, slot.party_size), {})[slot.slot_key] = slot
    return grouped
