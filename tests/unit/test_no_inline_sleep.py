"""Unit: STATE-03 — the state machine never waits out the confirmation delay in process.

D-43 makes confirmation stream-based: a PENDING slot pulls the restaurant's next poll forward
through the ZSET scheduler, and the confirmation arrives as another Kafka message. An inline
sleep would be the obvious shortcut, would look like it worked, and would quietly destroy the
property the whole design exists for — a service that scales past one restaurant and a replay
that reproduces confirmations from the raw stream alone.

The repo's CI ban-grep catches the synchronous ``time.sleep(`` but not the asynchronous form,
so only this test stands between the codebase and that shortcut. It duplicates the synchronous
gate at the unit tier too, so a developer sees it before pushing.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = REPO_ROOT / "services" / "state_machine"

SCANNED_FILES: tuple[Path, ...] = (
    *sorted(SERVICE_DIR.glob("*.py")),
    *sorted((SERVICE_DIR / "parsers").glob("*.py")),
)

_FULL_LINE_COMMENT = re.compile(r"^\s*#")
_ASYNC_SLEEP = re.compile(r"asyncio\.sleep\(")
_SYNC_SLEEP = re.compile(r"time\.sleep\(")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Strip full-line comments so an explanatory comment cannot satisfy or break the gate."""
    return [
        (lineno, line)
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if not _FULL_LINE_COMMENT.match(line)
    ]


def test_scanned_file_set_is_not_empty():
    """A glob that silently matched nothing would make both assertions below vacuous."""
    assert len(SCANNED_FILES) >= 8
    for path in SCANNED_FILES:
        assert path.is_file(), path
    names = {path.name for path in SCANNED_FILES}
    assert {"consumer.py", "main.py", "engine.py", "store.py"} <= names


def test_no_inline_asynchronous_sleep_in_the_state_machine():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
        for path in SCANNED_FILES
        for lineno, line in _code_lines(path)
        if _ASYNC_SLEEP.search(line)
    ]
    assert offenders == [], (
        "confirmation must be stream-based through the ZSET scheduler (D-43, STATE-03): "
        f"{offenders}"
    )


def test_no_blocking_sleep_in_the_state_machine():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
        for path in SCANNED_FILES
        for lineno, line in _code_lines(path)
        if _SYNC_SLEEP.search(line)
    ]
    assert offenders == []
