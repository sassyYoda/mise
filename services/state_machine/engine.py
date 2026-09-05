"""
Pure diff engine: normalised poll in, decisions out (D-38, D-41, D-44, D-49, D-53; STATE-02, STATE-04).

Functional core / imperative shell. This module performs no I/O of any kind, reads no clock and
draws no entropy — every timestamp in every decision comes from the message's polled_at_epoch_ms,
and all state access goes through the StateStore protocol. That is precisely what makes
byte-identical replay provable in CI (STATE-06); a single clock read here would make it flake.
Named symbols: StateStore, DiffEngine, MASS_CLOSURE_AUDIT_THRESHOLD
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

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

# Above this many closures in a single poll the shell logs a distinct auditable event, so the
# Phase 3 soft-ban canary has a training signal (research Pitfall 10). It is an observation
# threshold only: it never changes the diff outcome, which must stay deterministic.
MASS_CLOSURE_AUDIT_THRESHOLD: int = 5


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


class DiffEngine:
    """
    Tri-state slot diff (D-41). confirm_delay_ms is a REQUIRED argument: the engine imports no
    timing constant from a module another plan may be editing, and tests state it explicitly.

    last_close_count exposes how many Close decisions the most recent process() produced, for
    the mass-closure audit log in the consumer shell (research Pitfall 10).
    """

    def __init__(self, store: StateStore, confirm_delay_ms: int) -> None:
        self.store = store
        self.confirm_delay_ms = confirm_delay_ms
        self.last_close_count: int = 0

    async def process(self, parsed: ParsedPoll) -> list[Decision]:
        """Diff one normalised poll against stored state and return the decisions to execute."""
        await self.mark_success(parsed.restaurant_id, parsed.polled_at_epoch_ms)

        decisions: list[Decision] = []
        seen = _group_by_bucket(parsed.slots)
        needs_expedite = False
        close_count = 0

        # Buckets the poll observed, plus every bucket it covered (a covered bucket with zero
        # observed slots is a valid observation that closes and drops — D-39).
        for bucket in sorted(set(seen) | set(parsed.coverage)):
            date, party = bucket
            records = await self.store.get_slots(parsed.restaurant_id, date, party)
            observed = seen.get(bucket, {})

            for key, slot in sorted(observed.items()):
                record = records.get(key)
                if record is None or record.state is SlotState.UNAVAILABLE:
                    # Absent or previously closed: a re-open starts a brand-new cycle whose
                    # first_poll_id (and therefore event_id) differs from the previous one.
                    await self._open_cycle(parsed, slot, key)
                    needs_expedite = True
                elif record.state is SlotState.PENDING:
                    emit = await self._confirm_or_wait(parsed, slot, key, record)
                    if emit is None:
                        needs_expedite = True
                    else:
                        decisions.append(emit)
                else:
                    await self._refresh_available(parsed, slot, key, record)

            # Closure is bounded by coverage (D-38/D-38a): a bucket this poll did not actually
            # observe is never iterated for absence, which is what keeps party-4 slots alive.
            if bucket not in parsed.coverage:
                continue
            for key, record in sorted(records.items()):
                if key in observed:
                    continue
                if record.state is SlotState.PENDING:
                    # The false-positive guard: an unconfirmed ghost is dropped, never emitted.
                    await self.store.drop_slot(parsed.restaurant_id, date, party, key)
                elif record.state is SlotState.AVAILABLE:
                    close = await self._close(parsed, bucket, key, record)
                    if close is not None:
                        decisions.append(close)
                        close_count += 1

        if needs_expedite:
            # One expedite per restaurant per poll: the scheduler ZSET score is per job, not
            # per slot, so a burst of PENDING slots still pulls exactly one poll forward.
            decisions.append(Expedite(source=parsed.source, restaurant_id=parsed.restaurant_id))

        self.last_close_count = close_count
        return sorted(decisions, key=_sort_key)

    async def mark_unknown(self, restaurant_id: int, polled_at_epoch_ms: int) -> None:
        """
        Flag the restaurant UNKNOWN after an errored or unparseable poll (D-39, D-53).

        Monotonic in poll time: an observation at or before the last known success is dropped,
        so a stale polls.completed error cannot re-mark a healthy restaurant (Pitfall 2). Repeated
        errors keep the earliest onset, so the outcome does not depend on delivery order.
        No SlotRecord is touched — errors never move a slot toward UNAVAILABLE.
        """
        meta = await self.store.get_meta(restaurant_id)
        if meta.last_success_ms is not None and polled_at_epoch_ms <= meta.last_success_ms:
            return
        onset = (
            polled_at_epoch_ms
            if meta.unknown_since_ms is None
            else min(meta.unknown_since_ms, polled_at_epoch_ms)
        )
        await self.store.put_meta(
            restaurant_id,
            MetaRecord(unknown_since_ms=onset, last_success_ms=meta.last_success_ms),
        )

    async def mark_success(self, restaurant_id: int, polled_at_epoch_ms: int) -> None:
        """Record a successful poll and clear any UNKNOWN mark it post-dates (D-53)."""
        meta = await self.store.get_meta(restaurant_id)
        last_success = (
            polled_at_epoch_ms
            if meta.last_success_ms is None
            else max(meta.last_success_ms, polled_at_epoch_ms)
        )
        unknown_since = meta.unknown_since_ms
        if unknown_since is not None and polled_at_epoch_ms > unknown_since:
            unknown_since = None
        await self.store.put_meta(
            restaurant_id,
            MetaRecord(unknown_since_ms=unknown_since, last_success_ms=last_success),
        )

    async def _open_cycle(self, parsed: ParsedPoll, slot: Slot, key: str) -> None:
        """First sighting of a cycle: store PENDING and let the caller pull the next poll forward."""
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

    async def _refresh_available(
        self,
        parsed: ParsedPoll,
        slot: Slot,
        key: str,
        record: SlotRecord,
    ) -> None:
        """A still-open confirmed slot: refresh last_seen and the (rotatable) booking token."""
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
                confirmed_ms=record.confirmed_ms,
                event_id=record.event_id,
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

    async def _close(
        self,
        parsed: ParsedPoll,
        bucket: tuple[str, int],
        key: str,
        record: SlotRecord,
    ) -> Close | None:
        """A confirmed slot vanished from a successful covered poll: close its row (D-41, D-48)."""
        date, party = bucket
        await self.store.put_slot(
            parsed.restaurant_id,
            date,
            party,
            key,
            SlotRecord(
                state=SlotState.UNAVAILABLE,
                token=record.token,
                first_seen_ms=record.first_seen_ms,
                first_poll_id=record.first_poll_id,
                last_seen_ms=parsed.polled_at_epoch_ms,
                confirmed_ms=record.confirmed_ms,
                event_id=record.event_id,
            ),
        )
        if record.event_id is None or record.confirmed_ms is None:
            # An AVAILABLE record without an event id cannot be joined to a DB row; the state
            # transition still happens, but there is nothing for the shell to close.
            return None
        return Close(
            event_id=UUID(record.event_id),
            restaurant_id=parsed.restaurant_id,
            date=date,
            party_size=party,
            slot_key=key,
            confirmed_at_epoch_ms=record.confirmed_ms,
            last_seen_at_epoch_ms=parsed.polled_at_epoch_ms,
        )
