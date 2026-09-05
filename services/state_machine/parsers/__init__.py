"""
Per-source parser registry (D-37, D-66). The diff engine never branches on `raw.source`;
it calls parse_raw and lets this dict decide, so Phase 3 added Resy by registering one entry
and changing nothing in `engine.py` — the SC5 claim, pinned by the source scan in
`tests/unit/test_tracer_resy_raw_to_event.py`.
Named symbols: PARSER_REGISTRY, parse_raw, ParseError, UnsupportedSourceError
"""
from __future__ import annotations

from collections.abc import Callable

from services.state_machine.models import ParsedPoll
from services.state_machine.parsers.errors import ParseError, UnsupportedSourceError
from services.state_machine.parsers.opentable import parse_opentable
from services.state_machine.parsers.resy import parse_resy
from shared.events import AvailabilityRaw

PARSER_REGISTRY: dict[str, Callable[[AvailabilityRaw], ParsedPoll]] = {
    "opentable": parse_opentable,
    "resy": parse_resy,
}

__all__ = ["PARSER_REGISTRY", "ParseError", "ParsedPoll", "UnsupportedSourceError", "parse_raw"]


def parse_raw(raw: AvailabilityRaw) -> ParsedPoll:
    """
    Dispatch on raw.source. An unregistered source is UNKNOWN, not a crash.

    Both sources this project polls are registered as of Phase 3; the branch survives because
    `AvailabilityRaw.source` is a Literal the SCHEMA enforces and this dict is not, so a source
    added to one and not the other must degrade to UNKNOWN rather than KeyError a partition.
    """
    parser = PARSER_REGISTRY.get(raw.source)
    if parser is None:
        raise UnsupportedSourceError(f"no parser registered for source: {raw.source}")
    return parser(raw)
