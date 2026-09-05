"""
Mechanical purity guard for the replay-deterministic core (D-49; research Pitfall 8).

A single wall-clock read or random draw inside the engine, the models, or a parser makes
byte-identical replay fail intermittently — roughly one CI run in twenty, which is the worst
kind of failure to chase. This grep is the only mechanical defence, so it lives in a test.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Wall-clock reads and entropy draws, banned outright in the scanned modules.
BANNED_TOKENS: tuple[str, ...] = (
    "time.time(",
    "datetime.now(",
    "uuid4(",
    "random.",
)

SCANNED_FILES: tuple[Path, ...] = (
    REPO_ROOT / "services" / "state_machine" / "engine.py",
    REPO_ROOT / "services" / "state_machine" / "models.py",
    *sorted((REPO_ROOT / "services" / "state_machine" / "parsers").glob("*.py")),
)

_FULL_LINE_COMMENT = re.compile(r"^\s*#")


def _code_lines(path: Path) -> list[str]:
    """Strip full-line comments so an explanatory comment cannot satisfy or break the gate."""
    return [line for line in path.read_text().splitlines() if not _FULL_LINE_COMMENT.match(line)]


def test_scanned_file_set_is_not_empty():
    """A glob that silently matches nothing would make every assertion below vacuous."""
    assert len(SCANNED_FILES) >= 5
    for path in SCANNED_FILES:
        assert path.is_file(), path


def test_engine_models_and_parsers_contain_no_clock_or_randomness():
    offenders: list[str] = []
    for path in SCANNED_FILES:
        for lineno, line in enumerate(_code_lines(path), start=1):
            for token in BANNED_TOKENS:
                if token in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {token!r} in {line.strip()!r}")
    assert offenders == []


def test_core_never_imports_io_libraries():
    """The pure core must not reach Redis, Kafka or SQLAlchemy, directly or by import (D-49)."""
    banned_imports = re.compile(r"^(import|from)\s+(redis|aiokafka|sqlalchemy|httpx|requests)\b")
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {line.strip()}"
        for path in SCANNED_FILES
        for line in _code_lines(path)
        if banned_imports.match(line.strip())
    ]
    assert offenders == []


def test_core_never_blocks_the_event_loop():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {line.strip()}"
        for path in SCANNED_FILES
        for line in _code_lines(path)
        if "time.sleep(" in line or "asyncio.sleep(" in line
    ]
    assert offenders == []
