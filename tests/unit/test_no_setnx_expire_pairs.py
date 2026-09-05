"""ROADMAP Phase 2 success criterion 3 (mechanical half): no two-command idempotency claim.

A ``SETNX`` followed by a separate ``EXPIRE`` is not atomic — a crash between the two
leaves a key with no TTL, which never expires and permanently suppresses a real
notification (PITFALLS Pitfall 7). Every claim in this tree must route through
``shared.redis_keys.set_nx_ex``, which issues a single ``SET ... NX EX``.

This gate must stay green for the rest of the project.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("services", "shared", "scripts")

# The deprecated redis-py method: a dot, the name, then an open paren.
DEPRECATED_CLAIM = re.compile(r"\.\s*setnx\s*\(", re.IGNORECASE)


def _code_lines(path: Path) -> str:
    """Source with full-line comments stripped, so a comment can neither satisfy
    nor break the gate."""
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.strip().startswith("#")
    )


def _python_files() -> list[Path]:
    files: list[Path] = []
    for d in SCANNED_DIRS:
        files.extend(sorted((REPO_ROOT / d).rglob("*.py")))
    return files


def test_scanned_dirs_are_non_empty():
    """Guard the guard: a path typo must not make this test vacuously pass."""
    files = _python_files()
    assert len(files) > 10, f"expected a populated source tree, found {len(files)} files"


def test_no_two_command_setnx_expire_pairs():
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _python_files()
        if DEPRECATED_CLAIM.search(_code_lines(p))
    ]
    assert offenders == [], (
        f"Non-atomic SETNX claim found in {offenders}. "
        "Use shared.redis_keys.set_nx_ex (single SET NX EX) instead."
    )


def test_set_nx_ex_is_a_single_atomic_call():
    """The one sanctioned claim primitive carries nx= and ex= on one r.set(...) call."""
    src = (REPO_ROOT / "shared" / "redis_keys.py").read_text()
    match = re.search(r"async def set_nx_ex\(.*?\n\n", src, re.DOTALL)
    assert match, "set_nx_ex not found in shared/redis_keys.py"
    body = match.group(0)
    set_calls = re.findall(r"r\.set\((.*?)\)", body)
    assert len(set_calls) == 1, f"expected exactly one r.set(...) call, got {set_calls}"
    assert "nx=True" in set_calls[0]
    assert "ex=" in set_calls[0]
