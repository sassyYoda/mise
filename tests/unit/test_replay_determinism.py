"""
STATE-06 / ROADMAP SC2: byte-identical replay.

Two replays of the same committed raw fixture must produce the same bytes as each other AND
as the committed golden. That is the whole claim of this phase's portfolio artifact: given a
raw stream, the state machine regenerates the exact `availability.events` stream it produced
the first time, without re-polling OpenTable (D-49, D-50).

The golden is a tripwire on purpose. If NAMESPACE_MISE, the event_id recipe, or the
AvailabilityEvent field order ever change, this file fails — which is what we want, because
each of those silently invalidates every historical event id.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.replay_raw import (
    OutputPathError,
    canonical_topic,
    main,
    read_envelopes,
    replay,
    resolve_output_path,
    run_input_mode,
)
from shared.events import AvailabilityEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "raw_streams"
HAPPY_INPUT = FIXTURES / "happy.jsonl"
HAPPY_GOLDEN = FIXTURES / "happy.events.jsonl"


async def test_two_replays_are_byte_identical_and_match_the_golden(tmp_path: Path) -> None:
    """The SC2 claim: replay(x) == replay(x) == committed golden, as raw bytes."""
    out1 = tmp_path / "r1.jsonl"
    out2 = tmp_path / "r2.jsonl"

    assert await run_input_mode(HAPPY_INPUT, out1) == 0
    assert await run_input_mode(HAPPY_INPUT, out2) == 0

    first = out1.read_bytes()
    second = out2.read_bytes()
    assert first == second, "two replays of one fixture diverged"
    assert first == HAPPY_GOLDEN.read_bytes(), "replay output drifted from the committed golden"


async def test_the_golden_holds_exactly_one_confirmed_event() -> None:
    """Two polls 9000 ms apart confirm one slot: one line, one slot_opened event."""
    lines = await replay(read_envelopes(HAPPY_INPUT))
    assert len(lines) == 1

    event = AvailabilityEvent.model_validate_json(lines[0])
    assert event.event_type == "slot_opened"
    assert event.restaurant_id == 42
    assert event.date == "2026-05-01"
    assert event.time_slot == "19:00"
    assert event.party_size == 2
    assert event.seat_type == "bar"
    # produced_at is the CONFIRMING poll's timestamp, never a wall clock (D-45).
    assert event.first_seen_at_epoch_ms == 1788000000000
    assert event.confirmed_at_epoch_ms == 1788000009000
    assert event.produced_at_epoch_ms == 1788000009000


async def test_every_output_line_round_trips_through_the_single_serializer() -> None:
    """
    Each line is exactly `AvailabilityEvent.to_bytes()` — the producer's serializer.

    A second serializer in the replay writer (orjson, json.dumps(sort_keys=True), or
    model_dump(exclude_none=True)) would still round-trip semantically while producing
    different bytes than the wire, and the byte-identity claim would prove nothing about
    production (research Pitfall 7).
    """
    for line in await replay(read_envelopes(HAPPY_INPUT)):
        assert not line.endswith("\n")
        event = AvailabilityEvent.model_validate_json(line)
        assert event.to_bytes().decode() == line
        # Optional fields are EMITTED, never omitted: exclude_none would drop these keys.
        assert "seat_type" in json.loads(line)
        assert "booking_token" in json.loads(line)


async def test_an_empty_input_file_replays_to_a_zero_byte_output(tmp_path: Path) -> None:
    """The empty edge (STATE-06): no messages in, no events out, exit 0, zero bytes."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    out = tmp_path / "empty.events.jsonl"

    assert await run_input_mode(empty, out) == 0
    assert out.read_bytes() == b""


async def test_blank_lines_in_the_input_are_skipped(tmp_path: Path) -> None:
    """A trailing newline or a blank separator line is not a parse failure."""
    padded = tmp_path / "padded.jsonl"
    padded.write_text("\n" + HAPPY_INPUT.read_text() + "\n\n")
    assert await replay(read_envelopes(padded)) == await replay(read_envelopes(HAPPY_INPUT))


def test_an_output_path_outside_the_repository_root_is_refused(tmp_path: Path) -> None:
    """
    T-02-05: the script takes an output path from argv (research Security Domain V12).

    A RELATIVE path that escapes the repository root is refused; an explicit ABSOLUTE path is
    the caller opting in, and is allowed.
    """
    with pytest.raises(OutputPathError):
        resolve_output_path("../../mise-escape.jsonl")

    assert resolve_output_path(str(tmp_path / "ok.jsonl")) == tmp_path / "ok.jsonl"
    assert resolve_output_path("tests/fixtures/raw_streams/x.jsonl").is_relative_to(REPO_ROOT)


def test_main_exits_1_on_a_refused_output_path() -> None:
    """Exit code 1 is the usage / IO error code documented in the script header."""
    assert main(["--input", str(HAPPY_INPUT), "--output", "../../mise-escape.jsonl"]) == 1


def test_main_exits_1_on_a_missing_input_file(tmp_path: Path) -> None:
    assert main(["--input", str(tmp_path / "nope.jsonl"), "--output", str(tmp_path / "o.jsonl")]) == 1


def test_input_mode_never_reaches_the_persistence_or_consumer_layer() -> None:
    """
    D-49/D-50: a replay cannot mutate production state, so it must not even import the
    modules that could. `services.state_machine.consumer` drags in SQLAlchemy, the Kafka
    consumer group and the Redis client; none of them belong in a replay.
    """
    probe = (
        "import sys, scripts.replay_raw; "
        "leaked = [m for m in ('sqlalchemy', 'asyncpg', 'services.state_machine.consumer', "
        "'services.state_machine.persistence') if m in sys.modules]; "
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", f"replay imported production persistence: {result.stdout}"


def test_the_script_declares_no_second_serializer_and_no_production_client() -> None:
    """
    Import-scoped source gate. Byte-identity is only meaningful while the replay writer and the
    producer share one serializer (Pitfall 7), and read-only-ness is only structural while the
    script cannot open a Redis or Postgres connection at all.

    The ban is on the imported MODULE, resolved from the AST, not on the substring "redis"
    appearing anywhere in an import line. `shared.redis_keys` is a pure constants-and-helpers
    module — it holds the single `CONFIRM_DELAY_MS` literal replay must share with production
    (WR-07) and imports the redis client only under `TYPE_CHECKING` — so importing it opens
    nothing. Importing `redis` itself still cannot happen, and neither can constructing a
    client by any other route: the second half of this gate names the constructors.
    """
    source = (REPO_ROOT / "scripts" / "replay_raw.py").read_text()
    tree = ast.parse(source)

    imported_roots: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
            imported_roots.add(node.module.split(".")[0])

    for banned in ("redis", "sqlalchemy", "asyncpg", "psycopg"):
        assert banned not in imported_roots, f"replay must not import the {banned} client"
    assert "orjson" not in imported_roots, "replay must not declare a second serializer"
    assert "services.state_machine.consumer" not in imported_modules, (
        "replay must not import the production shell"
    )

    # No client may be constructed by any other route either.
    for constructor in ("from_url", "create_async_engine", "AIOKafkaProducer", "get_engine"):
        assert constructor not in source, f"replay must not construct {constructor}"

    # Match the AST, not the text: the script's own docstrings explain WHY exclude_none is
    # forbidden, and a text gate would be tripped by the explanation it exists to motivate
    # (the comment-aware-gate pattern established in 02-02).
    keywords = {
        kw.arg
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        for kw in node.keywords
    }
    assert "exclude_none" not in keywords
    assert "exclude_unset" not in keywords
    assert "to_bytes()" in source


def test_default_stdout_mode_emits_the_golden_and_nothing_else() -> None:
    """
    `replay_raw.py --input X > events.jsonl` must produce a usable file.

    shared.telemetry configures the stdlib root logger with `stream=sys.stdout` at DEBUG
    outside prod, so importing the state machine puts asyncio's selector chatter on the very
    stream --output falls back to. Without the stderr redirect this assertion fails with a
    "Using selector: KqueueSelector" line ahead of the event.
    """
    result = subprocess.run(
        [sys.executable, "scripts/replay_raw.py", "--input", str(HAPPY_INPUT)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == HAPPY_GOLDEN.read_bytes()


def test_the_help_text_documents_the_exclusive_upper_bound() -> None:
    """
    D-55 is a contract a human reads at 2 AM: --to-offset is EXCLUSIVE and defaults to
    end_offsets. If that is not in --help, the flag is a trap.
    """
    result = subprocess.run(
        [sys.executable, "scripts/replay_raw.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # argparse hard-wraps help text, so collapse whitespace before matching phrases.
    helptext = " ".join(result.stdout.lower().split())
    assert "exclusive" in helptext
    assert "end offsets" in helptext
    assert "offsets 2, 3 and 4" in helptext


def test_to_offset_without_from_offset_is_a_usage_error() -> None:
    """An exclusive bound with no range to bound is a mistake worth naming, not ignoring."""
    with pytest.raises(SystemExit) as exc:
        main(["--input", str(HAPPY_INPUT), "--to-offset", "5"])
    assert exc.value.code == 2  # argparse's own usage-error code


def test_a_source_topic_copy_still_routes_to_the_availability_raw_schema() -> None:
    """
    --topic lets an operator replay a mirror or per-environment copy of availability.raw.

    Routing on an exact name match would make every such topic "unrouted" and yield a silent
    zero-event replay — indistinguishable from a stream that legitimately confirmed nothing.
    """
    assert canonical_topic("availability.raw") == "availability.raw"
    assert canonical_topic("availability.raw.replay-ab12cd34") == "availability.raw"
    assert canonical_topic("staging.availability.raw") == "availability.raw"
    assert canonical_topic("polls.completed") == "polls.completed"
    assert canonical_topic("staging.polls.completed") == "polls.completed"


def test_the_makefile_exposes_replay_and_state_machine() -> None:
    """CONTEXT §Integration Points: both must be discoverable through `make help`."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    phony = next(ln for ln in makefile.splitlines() if ln.startswith(".PHONY"))
    for target in ("replay", "state-machine"):
        assert f"\n{target}:" in makefile, f"missing `{target}` target"
        assert f" {target} " in f" {phony} ", f"`{target}` missing from .PHONY"
        # The `## ` help comment is what `make help` greps for.
        line = next(ln for ln in makefile.splitlines() if ln.startswith(f"{target}:"))
        assert "## " in line, f"`{target}` would not appear in `make help`"


def test_the_env_example_documents_the_confirmation_window_and_the_crash_hook() -> None:
    """
    MISE_CRASH_AFTER may only appear alongside a TEST ONLY banner (research T-02-04): an
    operator who copies .env.example into a deployed environment must not silently arm a
    hook whose entire job is to SIGKILL the service.

    The confirmation window is documented in the same block, but as a NOTE rather than an
    assignment: no code reads `CONFIRM_DELAY_MS` from the environment (WR-06), and the replay
    goldens are only goldens because the window cannot be changed from a shell. The stricter
    form of this assertion lives in tests/unit/test_confirm_delay_is_not_configurable.py.
    """
    text = (REPO_ROOT / ".env.example").read_text()
    lines = text.splitlines()
    assert "CONFIRM_DELAY_MS" in text, "the window must still be explained to an operator"
    assert "CONFIRM_DELAY_MS=8000" not in lines, (
        "a variable no code reads must not be documented as settable"
    )

    crash_index = lines.index("MISE_CRASH_AFTER=")
    banner = "\n".join(lines[max(0, crash_index - 4) : crash_index])
    assert "TEST ONLY" in banner
    assert "must be unset" in banner
