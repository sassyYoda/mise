"""Integration: STATE-06 — bounded offset-range replay that cannot move production offsets.

D-55 makes ``--to-offset`` EXCLUSIVE, so ``[2, 5)`` consumes offsets 2, 3 and 4. D-50 makes
the replay consumer group-less: ``group_id=None`` plus ``assign``/``seek`` (never ``subscribe``)
means the tool has no committed offsets of its own and cannot disturb the ``state-machine``
group's. That is not an optimisation — it is what stops a portfolio demo from silently
rewinding or advancing the live pipeline.

Each test seeds its own uniquely named topic so message offsets are always 0..5 regardless of
execution order.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from scripts.replay_raw import fetch_offset_range, records_to_envelopes, replay, run_offset_mode
from shared.events import AvailabilityEvent, AvailabilityRaw
from shared.kafka import make_producer

pytestmark = pytest.mark.integration

RID = 42
DATE = "2026-05-01"
PARTY = 2
JOB = f"opentable:{RID}"
SEEDED_MESSAGES = 6
GROUP_ID = "state-machine"

# Base timestamp of the seeded stream. Messages are 9000 ms apart, so any two adjacent polls
# clear the 8000 ms confirmation window (D-44) and a bounded range still confirms the slot.
T0 = 1788300000000
STEP_MS = 9_000


def _response(token: str) -> dict[str, Any]:
    """A one-slot OpenTable payload; one seating type, so one slot and one event (D-36)."""
    return {
        "data": {
            "availability": [
                {
                    "restaurantId": RID,
                    "availability": [
                        {
                            "date": DATE,
                            "timeSlots": [
                                {"time": "19:00", "seatingTypes": ["bar"], "token": token}
                            ],
                        }
                    ],
                }
            ]
        }
    }


def _raw(index: int) -> AvailabilityRaw:
    """The index-th seeded poll. Every timestamp is derived, never read from a clock."""
    return AvailabilityRaw(
        poll_id=UUID(int=index + 1),
        source="opentable",
        restaurant_id=RID,
        polled_at_epoch_ms=T0 + index * STEP_MS,
        raw_response=_response("tok-offset-range"),
        request_params={"rid": RID, "dates": [DATE], "party_sizes": [PARTY]},
    )


async def _seed_topic(bootstrap: str) -> str:
    """Create a fresh single-partition topic and fill offsets 0..5 with availability.raw."""
    topic = f"availability.raw.replay-{uuid.uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        await admin.create_topics(
            [NewTopic(topic, num_partitions=1, replication_factor=1)]
        )
    finally:
        await admin.close()

    producer = await make_producer(bootstrap)
    try:
        for index in range(SEEDED_MESSAGES):
            await producer.send_and_wait(topic, value=_raw(index).to_bytes(), key=JOB)
    finally:
        await producer.stop()
    return topic


@pytest.mark.asyncio
async def test_the_upper_bound_is_exclusive(kafka_container) -> None:
    """D-55, verified in research §Pattern 5: [2, 5) is offsets 2, 3 and 4 — never 5."""
    bootstrap = kafka_container.get_bootstrap_server()
    topic = await _seed_topic(bootstrap)

    records = await fetch_offset_range(topic, bootstrap, 2, 5)
    assert [record.offset for record in records] == [2, 3, 4]


@pytest.mark.asyncio
async def test_omitting_the_upper_bound_stops_at_the_end_offsets(kafka_container) -> None:
    """
    Without --to-offset the bound is the topic's end_offsets, which is last offset + 1.

    The consumer must STOP there rather than block forever waiting for a message that will
    never be produced — an unbounded replay that hangs is useless as a debugging tool.
    """
    bootstrap = kafka_container.get_bootstrap_server()
    topic = await _seed_topic(bootstrap)

    records = await fetch_offset_range(topic, bootstrap, 0, None)
    assert [record.offset for record in records] == list(range(SEEDED_MESSAGES))


@pytest.mark.asyncio
async def test_an_empty_half_open_range_consumes_nothing_and_exits_2(
    kafka_container, tmp_path: Path
) -> None:
    """The adjacency edge: from == to is the empty interval, and exit 2 says so distinctly."""
    bootstrap = kafka_container.get_bootstrap_server()
    topic = await _seed_topic(bootstrap)

    assert await fetch_offset_range(topic, bootstrap, 3, 3) == []

    out = tmp_path / "empty.events.jsonl"
    assert await run_offset_mode(topic, bootstrap, 3, 3, out) == 2
    assert not out.exists()


@pytest.mark.asyncio
async def test_a_bounded_range_replays_through_the_production_engine(
    kafka_container, tmp_path: Path
) -> None:
    """Offset mode and --input mode are one code path: same engine, same serializer."""
    bootstrap = kafka_container.get_bootstrap_server()
    topic = await _seed_topic(bootstrap)

    out = tmp_path / "range.events.jsonl"
    assert await run_offset_mode(topic, bootstrap, 2, 5, out) == 0

    lines = out.read_text().splitlines()
    assert len(lines) == 1
    event = AvailabilityEvent.model_validate_json(lines[0])
    # The range starts at offset 2, so the cycle starts there — not at the topic's beginning.
    assert event.first_seen_at_epoch_ms == T0 + 2 * STEP_MS
    assert event.confirmed_at_epoch_ms == T0 + 3 * STEP_MS

    records = await fetch_offset_range(topic, bootstrap, 2, 5)
    assert await replay(records_to_envelopes(topic, records)) == lines


@pytest.mark.asyncio
async def test_replay_never_moves_the_state_machine_groups_committed_offsets(
    kafka_container, tmp_path: Path
) -> None:
    """
    T-02-06: the replay tool must be structurally incapable of committing an offset.

    A real ``state-machine`` group commits offset 2, a full replay runs, and the commit is
    still 2 afterwards. The tool also registers no consumer group of its own, which is what
    ``group_id=None`` buys.
    """
    bootstrap = kafka_container.get_bootstrap_server()
    topic = await _seed_topic(bootstrap)
    tp = TopicPartition(topic, 0)

    group = AIOKafkaConsumer(
        bootstrap_servers=bootstrap, group_id=GROUP_ID, enable_auto_commit=False
    )
    await group.start()
    try:
        group.assign([tp])
        await group.commit({tp: 2})
        before = await group.committed(tp)
        assert before == 2

        out = tmp_path / "all.events.jsonl"
        assert await run_offset_mode(topic, bootstrap, 0, None, out) == 0

        after = await group.committed(tp)
        assert after == before, "replay moved the state-machine group's committed offset"
    finally:
        await group.stop()

    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        groups = [entry[0] for entry in await admin.list_consumer_groups()]
    finally:
        await admin.close()
    replay_groups = [g for g in groups if g and "replay" in g]
    assert replay_groups == [], f"replay registered a consumer group: {replay_groups}"


@pytest.mark.asyncio
async def test_the_replay_consumer_never_subscribes(kafka_container) -> None:
    """
    ``assign()`` raises ``IllegalStateError`` if ``subscribe()`` was called first, and only
    ``subscribe`` joins a group. A single successful bounded read is therefore also proof the
    tool took the assign path — but pin the source too, so a future edit cannot quietly swap it.
    """
    source = (Path(__file__).resolve().parents[2] / "scripts" / "replay_raw.py").read_text()
    code = [ln for ln in source.splitlines() if not ln.strip().startswith("#")]
    assert not [ln for ln in code if ".subscribe(" in ln]
    assert [ln for ln in code if "group_id=None" in ln]

    bootstrap = kafka_container.get_bootstrap_server()
    topic = await _seed_topic(bootstrap)
    assert len(await fetch_offset_range(topic, bootstrap, 0, None)) == SEEDED_MESSAGES


@pytest.mark.asyncio
async def test_an_empty_topic_exits_2_rather_than_hanging(
    kafka_container, tmp_path: Path
) -> None:
    """
    A typo'd --topic (or a genuinely empty one) must terminate, not block forever.

    ``end_offsets`` is 0 on an empty topic, so the default upper bound makes the range empty
    and the documented "no messages found" exit code fires immediately.
    """
    bootstrap = kafka_container.get_bootstrap_server()
    empty_topic = f"availability.raw.empty-{uuid.uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        await admin.create_topics(
            [NewTopic(empty_topic, num_partitions=1, replication_factor=1)]
        )
    finally:
        await admin.close()

    out = tmp_path / "nothing.events.jsonl"
    assert await run_offset_mode(empty_topic, bootstrap, 0, None, out) == 2
    assert not out.exists()
