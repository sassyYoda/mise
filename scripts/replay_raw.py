#!/usr/bin/env python
"""
STATE-06: replay an availability.raw stream through the production DiffEngine and regenerate a
byte-identical availability.events stream.

Two modes, one code path. `--input` reads a tagged-envelope jsonl stream and needs no broker
(this is the CI-friendly path the byte-identity test uses); `--from-offset` reads a bounded
Kafka offset range (the portfolio demo, and the offline debugger for any production incident).
Both feed the same generator into the same `DiffEngine(MemoryStateStore(), ...)` the consumer
uses, and both write through the same `AvailabilityEvent.to_bytes()` the producer uses.

Replay is read-only BY CONSTRUCTION (D-49, D-50): it joins no consumer group, commits no
offset, and opens no Redis or Postgres connection, so it can never mutate production state.

Usage:
  uv run python scripts/replay_raw.py --input tests/fixtures/raw_streams/happy.jsonl
  uv run python scripts/replay_raw.py --from-offset 2 --to-offset 5 --output events.jsonl
Or:    make replay ARGS="--input tests/fixtures/raw_streams/happy.jsonl"

Exit codes:
  0 — replay completed (an empty result is a success, not an error)
  1 — usage or I/O error (unreadable input, malformed line, refused output path)
  2 — no messages found in the requested offset range

Named symbols: replay, read_envelopes, write_lines, resolve_output_path, run_input_mode,
               topic_partitions, resolve_partition, fetch_offset_range, canonical_topic,
               records_to_envelopes,
               run_offset_mode,
               route_diagnostics_to_stderr, InputError, OutputPathError, main
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import KafkaError
from pydantic import ValidationError

from services.state_machine.engine import DiffEngine
from services.state_machine.models import Decision, Emit
from services.state_machine.parsers import ParseError, parse_raw
from services.state_machine.store import MemoryStateStore
from shared.events import FAILED_POLL_STATUSES, AvailabilityRaw, PollCompleted
from shared.redis_keys import CONFIRM_DELAY_MS

# Topic names (D-27, D-45). Kept as literals rather than imported from the consumer module:
# importing that module would drag SQLAlchemy, a Kafka consumer group and a Redis client into
# a tool whose entire safety argument is that it has none of them.
RAW_TOPIC: Final[str] = "availability.raw"
COMPLETED_TOPIC: Final[str] = "polls.completed"

# T-02-05: the script takes an output path from argv, so writes are fenced to the repository
# root unless the caller names an absolute path explicitly (research Security Domain V12).
REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# One tagged-envelope line: {"topic": "<kafka topic>", "value": {<message body>}}. The tag is
# what lets a single fixture carry both availability.raw and polls.completed messages.
Envelope = dict[str, Any]


class InputError(Exception):
    """A jsonl input line that is not a well-formed tagged envelope."""


class OutputPathError(Exception):
    """A relative --output path that resolves outside the repository root (T-02-05)."""


def read_envelopes(path: Path) -> list[Envelope]:
    """Parse a tagged-envelope jsonl file. Blank lines are skipped, not an error."""
    envelopes: list[Envelope] = []
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                envelope = json.loads(text)
            except json.JSONDecodeError as exc:
                raise InputError(f"{path}:{lineno}: not valid JSON ({exc.msg})") from exc
            if not isinstance(envelope, dict) or "topic" not in envelope or "value" not in envelope:
                raise InputError(f'{path}:{lineno}: expected {{"topic": ..., "value": ...}}')
            envelopes.append(envelope)
    return envelopes


async def _handle_raw(engine: DiffEngine, value: Any) -> list[Decision]:
    """One availability.raw message: parse, or mark the restaurant UNKNOWN and move on (D-39)."""
    raw = AvailabilityRaw.model_validate(value)
    try:
        parsed = parse_raw(raw)
    except ParseError:
        # A transient error flows to UNKNOWN and moves no slot toward UNAVAILABLE (D-39, D-41).
        await engine.mark_unknown(raw.restaurant_id, raw.polled_at_epoch_ms)
        return []
    return await engine.process(parsed)


async def _handle_completed(engine: DiffEngine, value: Any) -> None:
    """
    One polls.completed message: every non-success status marks the restaurant UNKNOWN (D-47).

    Kept character-for-character equivalent to
    `services/state_machine/consumer.py::_handle_completed` (D-67a). These two functions live in
    different files with different lifecycles — a long-running service and an offline debugging
    CLI — and have already drifted apart once, each hard-coding its own `("error", "timeout")`
    tuple. A divergence here is worse than it looks: replay is the tool you reach for to explain
    a production incident, so a `banned` poll that means "failure" in production and "success"
    in replay makes the explanation wrong exactly when it matters.
    `tests/unit/test_banned_marks_unknown.py` drives both and asserts they agree.
    """
    completed = PollCompleted.model_validate(value)
    if completed.status == "success":
        return
    if completed.status not in FAILED_POLL_STATUSES:
        # Handled anyway — the branch above is `!= "success"`, not an allowlist — but a status
        # this build has never heard of is worth a line on stderr while replaying an incident.
        logging.getLogger(__name__).warning(
            "polls.completed carries unrecognised status %r; treated as a failed poll",
            completed.status,
        )
    await engine.mark_unknown(completed.restaurant_id, completed.polled_at_epoch_ms)


async def replay(
    envelopes: Iterable[Envelope],
    confirm_delay_ms: int = CONFIRM_DELAY_MS,
) -> list[str]:
    """
    Feed a stream of tagged envelopes through the production diff engine and return one output
    line per distinct emitted event, WITHOUT the trailing newline.

    `confirm_delay_ms` defaults to `shared.redis_keys.CONFIRM_DELAY_MS` — the SAME constant
    production compiles in, not a replay-local copy of its value — and never to an environment
    read: a golden file that depended on the caller's shell would not be a golden, and a second
    literal would let replay and production drift apart silently (WR-07).

    Events are de-duplicated by `event_id`, so a range that overlaps a prior emission still
    yields one line per distinct event (D-50). Serialisation is `AvailabilityEvent.to_bytes()`
    and nothing else — the single code path the producer uses, so the golden cannot drift from
    the bytes on the wire (research Pitfall 7). `exclude_none` / `exclude_unset` are never
    passed: they would make the output depend on how the model was constructed.
    """
    engine = DiffEngine(MemoryStateStore(), confirm_delay_ms=confirm_delay_ms)
    written: set[UUID] = set()
    lines: list[str] = []

    for envelope in envelopes:
        topic = envelope["topic"]
        if topic == RAW_TOPIC:
            decisions = await _handle_raw(engine, envelope["value"])
        elif topic == COMPLETED_TOPIC:
            await _handle_completed(engine, envelope["value"])
            decisions = []
        else:
            print(f"WARNING: skipping unrouted topic {topic!r}", file=sys.stderr)
            continue

        for decision in decisions:
            if not isinstance(decision, Emit):
                # Expedite and Close are consumer-shell side effects; neither is a wire event.
                continue
            if decision.event.event_id in written:
                continue
            written.add(decision.event.event_id)
            lines.append(decision.event.to_bytes().decode())

    return lines


def resolve_output_path(raw: str) -> Path:
    """
    Resolve --output, refusing a relative path that escapes the repository root (T-02-05).

    An ABSOLUTE path is the caller opting in explicitly and is allowed — that is what makes
    `--output /tmp/r1.jsonl` and a pytest `tmp_path` work.
    """
    given = Path(raw)
    resolved = given.resolve()
    if given.is_absolute():
        return resolved
    if not resolved.is_relative_to(REPO_ROOT):
        raise OutputPathError(
            f"refusing to write outside the repository root: {resolved} "
            f"(pass an absolute path if that is really what you want)"
        )
    return resolved


def write_lines(lines: Sequence[str], output_path: Path | None) -> None:
    """Write one event per line to `output_path`, or to stdout when it is None."""
    body = "".join(f"{line}\n" for line in lines)
    if output_path is None:
        sys.stdout.write(body)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")


async def run_input_mode(
    input_path: Path,
    output_path: Path | None,
    confirm_delay_ms: int = CONFIRM_DELAY_MS,
) -> int:
    """Replay a jsonl fixture. An empty input is a successful empty replay, never an error."""
    lines = await replay(read_envelopes(input_path), confirm_delay_ms)
    write_lines(lines, output_path)
    return 0


async def topic_partitions(topic: str, bootstrap: str) -> set[int]:
    """
    Return the partition ids of `topic`, or an empty set if it does not exist.

    An admin client rather than the consumer: `AIOKafkaConsumer.partitions_for_topic` reads
    `self._client.cluster`, which stays empty here because this consumer deliberately never
    subscribes, and `topics()` builds and then discards a throwaway `ClusterMetadata`. The
    admin client is metadata-only, so replay stays read-only by construction (D-50, T-02-06).
    """
    # `start()` INSIDE the try (IN-02): a failed metadata handshake otherwise leaks the
    # client's open connections. `close()` is safe on a client that never finished starting.
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    try:
        await admin.start()
        described = await admin.describe_topics([topic])
    finally:
        await admin.close()
    return {
        partition["partition"]
        for entry in described
        if entry.get("error_code", 0) == 0
        for partition in entry.get("partitions", [])
    }


async def resolve_partition(topic: str, bootstrap: str, requested: int | None) -> int:
    """
    Decide which partition an offset range refers to, refusing anything ambiguous.

    Kafka offsets are PER PARTITION, so `--from-offset 4000` names a different message on each
    one. Hardcoding partition 0 meant that the first time `availability.raw` is scaled past one
    partition — which the README's scaling section explicitly contemplates — a bounded replay
    would silently cover a fraction of the stream and exit 0 as though it had replayed
    everything. A single-partition topic still needs no flag; anything else must be named.
    """
    partitions = await topic_partitions(topic, bootstrap)
    if not partitions:
        raise InputError(f"topic {topic!r} does not exist, or has no partitions")
    if requested is None:
        if len(partitions) > 1:
            raise InputError(
                f"{topic} has {len(partitions)} partitions {sorted(partitions)} and Kafka "
                "offsets are per-partition, so --from-offset is ambiguous. Name one with "
                "--partition N."
            )
        return next(iter(partitions))
    if requested not in partitions:
        raise InputError(
            f"{topic} has no partition {requested} (partitions: {sorted(partitions)})"
        )
    return requested


async def fetch_offset_range(
    topic: str,
    bootstrap: str,
    from_offset: int,
    to_offset: int | None,
    partition: int | None = None,
) -> list[Any]:
    """
    Read a HALF-OPEN Kafka offset range `[from_offset, to_offset)` without joining a group.

    A group-less consumer plus `assign` + `seek` is the whole safety argument (D-50, T-02-06): a
    group-less consumer has no committed offsets, so this tool structurally cannot rewind or
    advance the `state-machine` group. `subscribe()` is never called — it is the call that
    joins a group, and `assign()` raises IllegalStateError if it ran first.

    `partition` defaults to "the topic's only partition", and a multi-partition topic is
    refused rather than silently read from partition 0 — see `resolve_partition`.

    `to_offset` defaults to the topic's `end_offsets`, which Kafka defines as last offset + 1;
    that is exactly why D-55 makes the flag EXCLUSIVE, so the default and an explicit bound
    mean the same thing. `assign` and `seek` are synchronous; `beginning_offsets`,
    `end_offsets` and `position` are coroutines (research §Pattern 5, verified transcript).
    """
    tp = TopicPartition(topic, await resolve_partition(topic, bootstrap, partition))
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap,
        group_id=None,
        enable_auto_commit=False,
    )
    await consumer.start()
    records: list[Any] = []
    try:
        consumer.assign([tp])
        end = (await consumer.end_offsets([tp]))[tp]
        upper = end if to_offset is None else min(to_offset, end)
        if from_offset >= upper:
            return []

        consumer.seek(tp, from_offset)
        while (await consumer.position(tp)) < upper:
            batches = await consumer.getmany(timeout_ms=2000, max_records=100)
            if not batches:
                # No more data. Breaking rather than looping keeps an unbounded replay from
                # spinning forever on a topic that will never fill.
                break
            done = False
            for batch in batches.values():
                for record in batch:
                    if record.offset >= upper:
                        done = True
                        break
                    records.append(record)
                if done:
                    break
            if done:
                break
    finally:
        await consumer.stop()
    return records


def canonical_topic(topic: str) -> str:
    """
    Map a source topic name onto the message SCHEMA it carries.

    `--topic` exists so an operator can replay a copy, a per-environment variant, or a
    differently-named mirror of `availability.raw`. Routing on an exact string match would
    make every such topic "unrouted", and the replay would silently produce zero events —
    which looks identical to a stream that legitimately confirmed nothing. Anything that is
    not recognisably a polls.completed topic carries availability.raw messages.
    """
    return COMPLETED_TOPIC if COMPLETED_TOPIC in topic else RAW_TOPIC


def records_to_envelopes(topic: str, records: Iterable[Any]) -> list[Envelope]:
    """
    Wrap Kafka records in the same tagged envelope the jsonl fixtures use.

    Raises InputError for a record that is not decodable JSON, naming the offset. An unguarded
    decode raised `JSONDecodeError` on a non-JSON record and `AttributeError` on a tombstone
    (`record.value is None`); `main()` catches neither, so both escaped as an unhandled
    traceback, the documented "1 — usage or I/O error" contract was not honoured, and the
    `--from-offset` path behaved differently from `--input` (which does wrap failures) for the
    very same defect.
    """
    role = canonical_topic(topic)
    envelopes: list[Envelope] = []
    for record in records:
        if record.value is None:
            raise InputError(f"{topic}[{record.offset}]: tombstone record has no value")
        try:
            value = json.loads(record.value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InputError(f"{topic}[{record.offset}]: {exc}") from exc
        envelopes.append({"topic": role, "value": value})
    return envelopes


async def run_offset_mode(
    topic: str,
    bootstrap: str,
    from_offset: int,
    to_offset: int | None,
    output_path: Path | None,
    confirm_delay_ms: int = CONFIRM_DELAY_MS,
    partition: int | None = None,
) -> int:
    """
    Replay a bounded Kafka offset range through the same engine `--input` mode uses.

    An empty range is distinct from an empty result: exit 2 says "there was nothing there to
    replay", which is a different thing from "the replay produced no events".
    """
    # Resolve the partition HERE so the diagnostic below can name the one that was actually
    # read (IN-04). It used to print the REQUESTED partition, which in the common
    # single-partition case is None — so the flag was omitted, the message degraded to the
    # bare topic name, and the exit-2 diagnostic never stated the one fact WR-11 exists to
    # make explicit. Passing the resolved id back into `fetch_offset_range` re-runs
    # `resolve_partition` as a validating no-op.
    resolved = await resolve_partition(topic, bootstrap, partition)
    records = await fetch_offset_range(topic, bootstrap, from_offset, to_offset, resolved)
    if not records:
        bound = "end_offsets" if to_offset is None else str(to_offset)
        where = f"{topic}[p{resolved}]"
        print(
            f"ERROR: no messages in {where}[{from_offset}, {bound}) — nothing to replay",
            file=sys.stderr,
        )
        return 2
    lines = await replay(records_to_envelopes(topic, records), confirm_delay_ms)
    write_lines(lines, output_path)
    return 0


def route_diagnostics_to_stderr() -> None:
    """
    Keep stdout pure data when --output is omitted.

    `shared.telemetry` runs `logging.basicConfig(stream=sys.stdout)` at import and defaults to
    DEBUG outside prod, so merely importing the state machine puts asyncio's selector chatter
    and every structlog line on STDOUT — the stream --output falls back to. Piping the tool
    into a file would then produce an unparseable mixture. In this script stdout is the event
    stream and nothing else; diagnostics belong on stderr.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            handler.setStream(sys.stderr)
    root.setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    """CLI surface. Defaults are read here, not at import, so nothing freezes the environment."""
    parser = argparse.ArgumentParser(
        prog="replay_raw.py",
        description=(
            "Replay an availability.raw stream through the production DiffEngine and regenerate "
            "a byte-identical availability.events stream (STATE-06)."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input",
        metavar="FILE",
        help="Replay a tagged-envelope jsonl stream; needs no broker.",
    )
    source.add_argument(
        "--from-offset",
        type=int,
        metavar="N",
        help="Inclusive lower bound of a Kafka offset range.",
    )
    parser.add_argument(
        "--to-offset",
        type=int,
        metavar="N",
        help=(
            "EXCLUSIVE upper bound of the offset range: offset N is never consumed, so "
            "--from-offset 2 --to-offset 5 replays offsets 2, 3 and 4. Defaults to the topic's "
            "end offsets (D-55)."
        ),
    )
    parser.add_argument("--topic", default=RAW_TOPIC, help=f"Source topic (default: {RAW_TOPIC}).")
    parser.add_argument(
        "--partition",
        type=int,
        metavar="N",
        help=(
            "Partition to replay. Kafka offsets are per-partition, so this is REQUIRED once "
            "the topic has more than one; a single-partition topic needs no flag."
        ),
    )
    parser.add_argument(
        "--bootstrap",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094"),
        metavar="SERVERS",
        help="Kafka broker list (default: $KAFKA_BOOTSTRAP_SERVERS or localhost:9094).",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help=(
            "Output path (default: stdout). A relative path resolving outside the repository "
            "root is refused; pass an absolute path to opt in."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, dispatch to one of the two modes, and map failures onto the exit codes."""
    route_diagnostics_to_stderr()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.input is not None and args.to_offset is not None:
        parser.error("--to-offset is only meaningful with --from-offset")
    if args.input is not None and args.partition is not None:
        parser.error("--partition is only meaningful with --from-offset")
    if args.partition is not None and args.partition < 0:
        parser.error("--partition must not be negative")
    if args.from_offset is not None and args.from_offset < 0:
        parser.error("--from-offset must not be negative")
    if args.to_offset is not None and args.from_offset is not None and args.to_offset < args.from_offset:
        parser.error("--to-offset is the EXCLUSIVE upper bound and must not precede --from-offset")

    try:
        output_path = resolve_output_path(args.output) if args.output else None
    except OutputPathError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        if args.input is not None:
            return asyncio.run(run_input_mode(Path(args.input), output_path))
        return asyncio.run(
            run_offset_mode(
                args.topic,
                args.bootstrap,
                args.from_offset,
                args.to_offset,
                output_path,
                partition=args.partition,
            )
        )
    except (InputError, OSError, ValidationError, KafkaError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
