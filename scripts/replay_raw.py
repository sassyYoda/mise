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
               run_offset_mode, route_diagnostics_to_stderr, InputError, OutputPathError, main
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

from pydantic import ValidationError

from services.state_machine.engine import DiffEngine
from services.state_machine.models import DEFAULT_CONFIRM_DELAY_MS, Decision, Emit
from services.state_machine.parsers import ParseError, parse_raw
from services.state_machine.store import MemoryStateStore
from shared.events import AvailabilityRaw, PollCompleted

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
    """One polls.completed message: only error/timeout matters here (D-47)."""
    completed = PollCompleted.model_validate(value)
    if completed.status in ("error", "timeout"):
        await engine.mark_unknown(completed.restaurant_id, completed.polled_at_epoch_ms)


async def replay(
    envelopes: Iterable[Envelope],
    confirm_delay_ms: int = DEFAULT_CONFIRM_DELAY_MS,
) -> list[str]:
    """
    Feed a stream of tagged envelopes through the production diff engine and return one output
    line per distinct emitted event, WITHOUT the trailing newline.

    `confirm_delay_ms` defaults to the compiled-in constant rather than an environment read: a
    golden file that depended on CONFIRM_DELAY_MS in the caller's shell would not be a golden.

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
    confirm_delay_ms: int = DEFAULT_CONFIRM_DELAY_MS,
) -> int:
    """Replay a jsonl fixture. An empty input is a successful empty replay, never an error."""
    lines = await replay(read_envelopes(input_path), confirm_delay_ms)
    write_lines(lines, output_path)
    return 0


async def run_offset_mode(
    topic: str,
    bootstrap: str,
    from_offset: int,
    to_offset: int | None,
    output_path: Path | None,
    confirm_delay_ms: int = DEFAULT_CONFIRM_DELAY_MS,
) -> int:
    """Bounded Kafka offset-range replay — implemented in task 3 of plan 02-04."""
    print("ERROR: --from-offset is not yet implemented", file=sys.stderr)
    return 1


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
    args = build_parser().parse_args(argv)

    try:
        output_path = resolve_output_path(args.output) if args.output else None
    except OutputPathError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        if args.input is not None:
            return asyncio.run(run_input_mode(Path(args.input), output_path))
        return asyncio.run(
            run_offset_mode(args.topic, args.bootstrap, args.from_offset, args.to_offset, output_path)
        )
    except (InputError, OSError, ValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
