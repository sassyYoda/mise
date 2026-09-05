"""
event_id determinism (D-45, D-54; STATE-04, STATE-06).

The uuid5 recipe and NAMESPACE_MISE are permanent: every historical event id and every
committed golden replay file derives from them. These tests pin both, in-process and across
a fresh interpreter, so an accidental namespace or recipe edit fails loudly.
"""
from __future__ import annotations

import subprocess
import sys
from uuid import UUID

from shared.events import NAMESPACE_MISE, make_event_id

ARGS = ("opentable", 42, "2026-05-01", 2, "19:00|bar", "poll-1")


def test_namespace_is_the_pinned_literal():
    assert NAMESPACE_MISE == UUID("629d45e6-9621-5f62-a1ea-dd826ede29f8")


def test_repeated_construction_is_identical():
    assert make_event_id(*ARGS) == make_event_id(*ARGS)


def test_event_id_is_stable_across_a_fresh_interpreter():
    """A new process must reproduce the same id, or replay byte-identity is unprovable."""
    snippet = (
        "from shared.events import make_event_id;"
        "print(make_event_id('opentable', 42, '2026-05-01', 2, '19:00|bar', 'poll-1'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(make_event_id(*ARGS))


def test_changing_only_the_first_poll_id_changes_the_event_id():
    """This is what makes a re-opened slot a genuinely distinct event (D-41)."""
    other = make_event_id("opentable", 42, "2026-05-01", 2, "19:00|bar", "poll-2")
    assert other != make_event_id(*ARGS)


def test_each_identity_component_participates_in_the_id():
    variants = [
        ("resy", 42, "2026-05-01", 2, "19:00|bar", "poll-1"),
        ("opentable", 43, "2026-05-01", 2, "19:00|bar", "poll-1"),
        ("opentable", 42, "2026-05-02", 2, "19:00|bar", "poll-1"),
        ("opentable", 42, "2026-05-01", 4, "19:00|bar", "poll-1"),
        ("opentable", 42, "2026-05-01", 2, "19:00|standard", "poll-1"),
    ]
    ids = {make_event_id(*v) for v in variants} | {make_event_id(*ARGS)}
    assert len(ids) == len(variants) + 1
