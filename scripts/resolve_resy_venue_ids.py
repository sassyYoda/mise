#!/usr/bin/env python
"""
Fill the numeric `resy_venue_id` values that D-63a deliberately leaves null.

STATUS: pending-human — this script has never been run for real.
    It requires a genuine `RESY_API_KEY`, captured by the procedure in
    docs/runbooks/resy-cookie-capture.md (Chrome DevTools -> Network -> any
    api.resy.com request -> the `Authorization: ResyAPI api_key="..."` header). No
    such key exists in this repository or in CI, so every id in
    scripts/seed/restaurants.yml is still null and no Resy poll job exists.

    Nothing in Phase 3 BLOCKS on this. The fleet is disabled by default
    (`RESY_ENABLED=false`), the seed skips a null id, and every code path is
    exercised against fixtures and a local stub. This script is the handoff, not a
    gate: when a human has the key, they run it, review the diff, and re-seed.

Why the field had to be split at all (research B-4): every `resy_venue_id` in the
seed was a URL slug like "carbone-new-york-new-york". Resy's /4/find takes a NUMERIC
venue id; the poller's job descriptor is `resy:{resy_venue_id}` and `poll_loop`
parses it back with `int()`. A slug there raises, and the poller logs
`invalid_restaurant_id` and continues WITHOUT releasing the job — so the job sits in
`sched:polls:inflight` and the reaper re-enqueues it forever. 03-03 renamed the
string field to `resy_url_slug` and made `resy_venue_id` an integer-or-null. No
placeholder integer was minted: a fabricated id is still a valid job, so the fleet
would poll a stranger's venue with no signal the data was invented (T-03-10).

Usage:
    uv run python scripts/resolve_resy_venue_ids.py --dry-run
    RESY_API_KEY=... uv run python scripts/resolve_resy_venue_ids.py
    RESY_API_KEY=... uv run python scripts/resolve_resy_venue_ids.py --slug carbone-nyc

Exit codes (the scripts/check_poll_success.py convention):
    0 — every requested slug was resolved
    1 — one or more lookups failed (the ones that succeeded are still written)
    2 — preconditions not met: no RESY_API_KEY, a --dry-run, or an unknown --slug
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.poller.config import resy_api_base, resy_api_key
from shared.http_client import close_async_client, get_async_client

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YAML_PATH = REPO_ROOT / "scripts" / "seed" / "restaurants.yml"
RUNBOOK = "docs/runbooks/resy-cookie-capture.md"

EXIT_OK = 0
EXIT_LOOKUP_FAILED = 1
EXIT_PRECONDITION = 2

_URL_SLUG_LINE = re.compile(r'^(\s*)resy_url_slug:\s*"?([^"#\s]+)"?\s*(?:#.*)?$')
_SLUG_LINE = re.compile(r'^(\s*)slug:\s*"?([^"#\s]+)"?\s*(?:#.*)?$')
_VENUE_ID_LINE = re.compile(r"^(\s*)resy_venue_id:\s*([^#\s]+)\s*(?:#.*)?$")
_ENTRY_START = re.compile(r"^\s*-\s")


@dataclass(frozen=True)
class Target:
    """One YAML entry awaiting a numeric venue id, and where to write it."""

    slug: str  # the mise slug (the entry's own `slug:` key)
    url_slug: str  # the human Resy URL slug, the resolver's input
    venue_line: int  # 0-based index of this entry's `resy_venue_id:` line
    indent: str  # that line's indentation, so the rewrite matches the file


def parse_targets(text: str) -> list[Target]:
    """
    Every entry with a `resy_url_slug` and a non-numeric `resy_venue_id`.

    Line-based rather than `yaml.safe_load` + `yaml.safe_dump` on purpose: the seed file
    carries ~70 lines of curation sources, schema documentation and two PLACEHOLDER
    WARNING blocks, and `safe_dump` deletes every one of them silently. The comments are
    the part a human reads before trusting an id, so they are the part that must survive.
    """
    lines = text.splitlines()
    targets: list[Target] = []

    slug: str | None = None
    url_slug: str | None = None
    venue_line: int | None = None
    indent = "    "

    def flush() -> None:
        if slug and url_slug and venue_line is not None:
            targets.append(
                Target(slug=slug, url_slug=url_slug, venue_line=venue_line, indent=indent)
            )

    for lineno, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if _ENTRY_START.match(line) and "name:" in line:
            flush()
            slug, url_slug, venue_line = None, None, None
        if (match := _SLUG_LINE.match(line)) is not None:
            slug = match.group(2)
        elif (match := _URL_SLUG_LINE.match(line)) is not None:
            url_slug = match.group(2)
        elif (match := _VENUE_ID_LINE.match(line)) is not None:
            # Only an UNRESOLVED entry is a target. Re-looking-up an id a human already
            # verified would burn a rate-limited API call and risk overwriting a correct
            # value with whatever the [ASSUMED] endpoint returns today.
            if match.group(2) == "null":
                venue_line = lineno
                indent = match.group(1)
    flush()
    return targets


def resolve_yaml_path(raw: str | None) -> Path:
    """
    Resolve `--yaml` and REFUSE anything outside the repository (T-03-13, ASVS V12).

    `Path.is_relative_to` rather than a string prefix: `str(p).startswith(str(root))`
    accepts `/…/mise-evil/restaurants.yml` for a root of `/…/mise`, which is a sibling
    directory an attacker controls, not a subdirectory.
    """
    candidate = (DEFAULT_YAML_PATH if raw is None else Path(raw)).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    root = REPO_ROOT.resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(
            f"{resolved} is outside the repository ({root}). This script only edits the "
            "seed data it ships with."
        )
    return resolved


def apply_resolution(text: str, target: Target, venue_id: int) -> str:
    """Rewrite exactly one line: `resy_venue_id: null  # TODO(...)` -> the integer."""
    lines = text.splitlines(keepends=True)
    newline = "\n" if lines[target.venue_line].endswith("\n") else ""
    today = datetime.now(UTC).date().isoformat()
    # The provenance comment is not decoration. A bare integer in a diff is unreviewable;
    # naming the slug it came from is what lets a human open
    # https://resy.com/cities/ny/<slug> and confirm the id points at the right restaurant.
    lines[target.venue_line] = (
        f"{target.indent}resy_venue_id: {venue_id}"
        f"  # resolved {today} from resy_url_slug {target.url_slug!r}{newline}"
    )
    return "".join(lines)


def write_atomically(path: Path, text: str) -> None:
    """
    Write through a temp file in the SAME directory, then rename (ASVS V12).

    A plain `path.write_text` truncates first, so a Ctrl-C or a full disk between the
    truncate and the write leaves the 55-entry hand-curated seed file empty or half
    written. `os.replace` is atomic within a filesystem, and the temp file is created
    beside the target so the rename never crosses one. The temp file is removed on ANY
    failure, so an interrupted run leaves no litter for the next one to trip over.
    """
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        # BaseException, not Exception: KeyboardInterrupt is the interruption this guard
        # exists for, and it does not inherit from Exception.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


async def _resolve_one(client: Any, url_slug: str, api_key: str) -> int:
    """
    Look up ONE numeric venue id. The only function in this file that touches the network.

    TODO(spike): the endpoint below is [ASSUMED] (research A4). No public documentation
    confirms `GET {RESY_API_BASE}/3/venue?url_slug={slug}&location=ny`, and nobody has
    been able to call it — resolving that needs the DevTools capture in
    docs/runbooks/resy-cookie-capture.md. Everything unverified is deliberately confined
    to this one function: correcting the path, the query parameters or the response field
    is a single-function edit, and the exception it raises is caught by the caller and
    reported per slug rather than aborting the run.
    """
    url = f"{resy_api_base()}/3/venue"
    response = await client.get(
        url,
        params={"url_slug": url_slug, "location": "ny"},
        headers={
            "Authorization": f'ResyAPI api_key="{api_key}"',
            "Accept": "application/json",
            "X-Origin": "https://resy.com",
        },
    )
    if response.status_code != 200:
        # The BODY is deliberately not included: a Resy error page can echo request
        # headers, and this message is printed (T-03-11).
        raise RuntimeError(f"HTTP {response.status_code} for url_slug={url_slug!r}")
    payload = response.json()
    venue_id = payload.get("id", {}).get("resy") if isinstance(payload, dict) else None
    if venue_id is None:
        raise RuntimeError(f"no venue id in the response for url_slug={url_slug!r}")
    return int(venue_id)


def _redact(message: str, api_key: str | None) -> str:
    """Strip the key from any text on its way to a terminal (T-03-11).

    Belt and braces: no message here is BUILT from the key, but an exception raised by an
    HTTP client can quote the request that carried it, and this function is the last thing
    between that exception and the operator's scrollback.
    """
    if not api_key:
        return message
    return message.replace(api_key, "***REDACTED***")


def _select(targets: list[Target], slug: str | None) -> list[Target] | None:
    """Apply `--slug`. Returns None when the filter matched nothing (an exit-2 case)."""
    if slug is None:
        return targets
    chosen = [t for t in targets if slug in (t.slug, t.url_slug)]
    return chosen or None


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve numeric Resy venue ids into the seed YAML (human-gated).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the work set and exit 2; makes no network call and writes nothing",
    )
    parser.add_argument("--slug", help="restrict to one entry (its slug or resy_url_slug)")
    parser.add_argument("--yaml", help=f"seed file to edit (default {DEFAULT_YAML_PATH})")
    args = parser.parse_args(argv)

    try:
        yaml_path = resolve_yaml_path(args.yaml)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION

    text = yaml_path.read_text()
    targets = parse_targets(text)
    selected = _select(targets, args.slug)
    if selected is None:
        print(
            f"REFUSED: --slug {args.slug!r} matched no unresolved entry in {yaml_path}. "
            f"It may already be resolved, or it may not be on Resy. Unresolved slugs: "
            f"{', '.join(t.slug for t in targets) or '(none)'}",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION

    print(f"{len(selected)} Resy venue(s) unresolved in {yaml_path}:")
    for target in selected:
        print(f"  {target.slug:<28} resy_url_slug={target.url_slug}")

    api_key = resy_api_key()

    if args.dry_run:
        print(
            f"\nDRY RUN — no network call was made and {yaml_path.name} was not written.\n"
            f"To resolve for real, capture RESY_API_KEY per {RUNBOOK} and re-run without "
            "--dry-run."
        )
        return EXIT_PRECONDITION

    if api_key is None:
        print(
            f"REFUSED: RESY_API_KEY is not set, so no lookup is possible. Capture it per "
            f"{RUNBOOK}, then re-run. ({len(selected)} venue(s) still unresolved.)",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION

    client = get_async_client()
    failures = 0
    resolved = 0
    try:
        for target in selected:
            try:
                venue_id = await _resolve_one(client, target.url_slug, api_key)
            except Exception as exc:  # noqa: BLE001 — reported per slug, never fatal
                failures += 1
                print(
                    f"  FAILED {target.slug}: {_redact(str(exc), api_key)}",
                    file=sys.stderr,
                )
                continue
            # A slug or a float here is the exact poison this whole plan exists to
            # prevent, so it is refused at the boundary rather than written and
            # discovered later by poll_loop (T-03-10, research B-4).
            if isinstance(venue_id, bool) or not isinstance(venue_id, int):
                failures += 1
                print(
                    f"  FAILED {target.slug}: the endpoint returned "
                    f"{type(venue_id).__name__}, not an integer venue id — refusing to "
                    "write it. The endpoint shape is [ASSUMED]; see the TODO(spike) in "
                    "_resolve_one.",
                    file=sys.stderr,
                )
                continue
            text = apply_resolution(text, target, venue_id)
            resolved += 1
            print(f"  resolved {target.slug} -> {venue_id}")
    finally:
        await close_async_client()

    if resolved:
        # Written even when some lookups failed: discarding the successes would make the
        # operator re-run every lookup against a rate-limited third-party API.
        write_atomically(yaml_path, text)
        print(
            f"\nWrote {resolved} venue id(s) to {yaml_path}. REVIEW THE DIFF before "
            "committing: open https://resy.com/cities/ny/<resy_url_slug> and confirm each "
            "id points at the restaurant named in the same entry. Then re-run "
            "`RESY_ENABLED=true make seed`."
        )
    if failures:
        print(f"{failures} lookup(s) failed.", file=sys.stderr)
        return EXIT_LOOKUP_FAILED
    return EXIT_OK


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
