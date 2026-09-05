"""
Per-source parser registry (D-37). The diff engine never branches on `raw.source`;
it calls parse_raw and lets this dict decide, so Phase 3 adds Resy by registering one entry.
Named symbols: PARSER_REGISTRY, parse_raw, ParseError, UnsupportedSourceError
"""
from __future__ import annotations

from collections.abc import Callable

from services.state_machine.models import ParsedPoll
from services.state_machine.parsers.errors import ParseError, UnsupportedSourceError
from services.state_machine.parsers.opentable import parse_opentable
from shared.events import AvailabilityRaw

PARSER_REGISTRY: dict[str, Callable[[AvailabilityRaw], ParsedPoll]] = {
    "opentable": parse_opentable,
}

__all__ = ["PARSER_REGISTRY", "ParseError", "ParsedPoll", "UnsupportedSourceError", "parse_raw"]


def parse_raw(raw: AvailabilityRaw) -> ParsedPoll:
    """Dispatch on raw.source. An unregistered source (`resy` until Phase 3) is UNKNOWN, not a crash."""
    parser = PARSER_REGISTRY.get(raw.source)
    if parser is None:
        raise UnsupportedSourceError(f"no parser registered for source: {raw.source}")
    return parser(raw)
