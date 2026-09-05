"""Unit: WR-06/WR-07 — one confirmation-delay constant, and it is not an environment variable.

`.env.example` and the README both advertised `CONFIRM_DELAY_MS` as a tunable with a default
of 8000, and the README stated "Every variable is read lazily, inside run()". No code has ever
called `os.getenv("CONFIRM_DELAY_MS")`: it is a module constant, so setting it in a deployment
or a test silently did nothing — the most expensive class of configuration bug to debug.

Separately, the window was declared TWICE (`models.DEFAULT_CONFIRM_DELAY_MS` for replay,
`redis_keys.CONFIRM_DELAY_MS` for production). They agreed only by coincidence, and changing
one would leave every golden file asserting a window production no longer used.
"""
from __future__ import annotations

import re
from pathlib import Path

from shared.redis_keys import CONFIRM_DELAY_MS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("services", "shared", "scripts")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for d in SCANNED_DIRS:
        files.extend(sorted((REPO_ROOT / d).rglob("*.py")))
    return files


def test_scanned_dirs_are_non_empty() -> None:
    """Guard the guard: a path typo must not make these tests vacuously pass."""
    assert len(_python_files()) > 10


def test_no_code_reads_confirm_delay_ms_from_the_environment() -> None:
    """If this ever starts failing, the documentation must be un-deleted, not the test."""
    readers = [
        str(p.relative_to(REPO_ROOT))
        for p in _python_files()
        if re.search(r"""getenv\(\s*["']CONFIRM_DELAY_MS""", p.read_text())
        or re.search(r"""environ\[\s*["']CONFIRM_DELAY_MS""", p.read_text())
    ]
    assert readers == [], (
        f"{readers} now reads CONFIRM_DELAY_MS from the environment. Either revert that, or "
        "restore the .env.example entry and the README row that this fix removed."
    )


def test_env_example_does_not_advertise_confirm_delay_ms_as_a_variable() -> None:
    """A documented knob no code reads is worse than no knob at all."""
    lines = (REPO_ROOT / ".env.example").read_text().splitlines()
    assignments = [
        line for line in lines
        if not line.lstrip().startswith("#") and line.split("=", 1)[0].strip() == "CONFIRM_DELAY_MS"
    ]
    assert assignments == [], f".env.example still declares {assignments}"
def test_there_is_exactly_one_confirmation_delay_constant() -> None:
    """WR-07: replay and production must not be able to drift apart."""
    import services.state_machine.models as models

    assert not hasattr(models, "DEFAULT_CONFIRM_DELAY_MS"), (
        "a second confirm-delay literal is back; replay and production can now silently "
        "disagree and every golden file would assert a window production no longer uses"
    )
    assert CONFIRM_DELAY_MS == 8_000


def test_replay_uses_the_production_constant() -> None:
    """The golden files and the wire must be produced with the same window."""
    import scripts.replay_raw as replay_raw

    assert replay_raw.CONFIRM_DELAY_MS is CONFIRM_DELAY_MS
