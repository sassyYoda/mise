"""
Golden-file JSON fixtures for the Resy adapter, parser and stub-server tests (D-64, D-66).

Every body below is `[ASSUMED]`. No call to resy.com is permitted in this phase, so the shape
comes from two independent public captures rather than from the wire:
`results.venues[].slots[] {date{start,end}, config{type,token,id}, size{min,max}}`
(03-RESEARCH.md §Assumptions Log A1/A2). Confirm each one against a live `/4/find` response
during the DevTools capture documented in `docs/runbooks/resy-cookie-capture.md`, then delete
the `TODO(spike):` marker above it.

These constants are the ONE place the assumed shape is written down. `parse_resy`,
`tests/unit/test_parsers_resy.py`, `tests/unit/test_tracer_resy_raw_to_event.py` and the
Phase-3 stub server all read them, so a shape correction after the spike is a single-file edit
and fails loudly in one place rather than drifting across thirty.

Bodies are the `body` value of ONE D-64 envelope entry — the envelope itself
(`{"requests": [{"date", "party_size", "status", "body"}, ...]}`) is built by
`tests/unit/factories.py :: make_resy_envelope`, never here.

Named symbols: RESY_SUCCESS_RESPONSE, RESY_EMPTY_VENUES_RESPONSE,
RESY_MISSING_RESULTS_RESPONSE, RESY_RESULTS_NOT_A_MAPPING_RESPONSE,
RESY_MALFORMED_SLOTS_RESPONSE, RESY_DUPLICATE_SLOT_RESPONSE, RESY_RATE_LIMIT_RESPONSE,
RESY_CHALLENGE_HTML, RESY_FIXTURE_VENUE_ID
"""
from __future__ import annotations

from typing import Any

# The numeric Resy venue id every fixture below describes. `resy_venue_id` values in
# scripts/seed/restaurants.yml are URL slugs today (D-63a); this is a stand-in numeric id so
# the fixtures and the tests agree on one restaurant.
RESY_FIXTURE_VENUE_ID: int = 4242

# Minimal success response — 1 venue, 3 slots across 2 seating types and 2 times.
#
# Slot 3 deliberately carries `config.id` but NO `config.token`: research A2 found public
# captures showing both field names, so `parse_resy` must fall back to `id` and this fixture
# is what proves the fallback is exercised rather than merely written.
#
# TODO(spike): confirm the exact `/4/find` JSON structure against a live Resy response.
RESY_SUCCESS_RESPONSE: dict[str, Any] = {
    "results": {
        "venues": [
            {
                "venue": {"id": {"resy": RESY_FIXTURE_VENUE_ID}, "name": "Fixture Venue"},
                "slots": [
                    {
                        "date": {"start": "2026-05-01 19:00:00", "end": "2026-05-01 21:00:00"},
                        "config": {
                            "type": "Dining Room",
                            "token": "rgs-dining-room-1900",
                            "id": 111,
                        },
                        "size": {"min": 2, "max": 4},
                    },
                    {
                        "date": {"start": "2026-05-01 19:00:00", "end": "2026-05-01 21:00:00"},
                        "config": {"type": "Bar", "token": "rgs-bar-1900", "id": 222},
                        "size": {"min": 1, "max": 2},
                    },
                    {
                        "date": {"start": "2026-05-01 21:30:00", "end": "2026-05-01 23:00:00"},
                        # No `token` — A2's fallback path.
                        "config": {"type": "Patio", "id": 333},
                        "size": {"min": 2, "max": 4},
                    },
                ],
            }
        ]
    }
}

# A 200 that observed the venue and found nothing bookable.
#
# This is Pitfall 10: at parse time this is INDISTINGUISHABLE from a soft ban that returns an
# empty page with a 200. The parser therefore treats it as a truthful zero-slot observation
# (coverage non-empty, `slots == ()`) — a fully booked venue must close its slots — and the
# POLL-06 canary, which has a rolling baseline the parser does not, is what tells the two
# apart.
#
# TODO(spike): confirm Resy returns `venues: []` rather than a null or a missing key.
RESY_EMPTY_VENUES_RESPONSE: dict[str, Any] = {"results": {"venues": []}}

# A 200 whose body carries no `results` key at all. Not an observation of nothing: an
# observation that did not happen. `parse_resy` raises ParseError -> UNKNOWN (D-39).
#
# TODO(spike): confirm what Resy actually returns for a venue id it does not know.
RESY_MISSING_RESULTS_RESPONSE: dict[str, Any] = {"tally": {"total": 0}}

# `results` present but the wrong TYPE. Kept as a named fixture rather than inlined in a test
# so the parser matrix never invents its own payload shape.
RESY_RESULTS_NOT_A_MAPPING_RESPONSE: dict[str, Any] = {"results": []}

# One usable slot surrounded by four unusable ones. Each bad entry exercises a different
# per-slot type guard, and the parser must `continue` past all four rather than raise: one
# malformed slot may not blind the whole restaurant.
RESY_MALFORMED_SLOTS_RESPONSE: dict[str, Any] = {
    "results": {
        "venues": [
            {
                "venue": {"id": {"resy": RESY_FIXTURE_VENUE_ID}},
                "slots": [
                    # date.start is an int, not a string.
                    {
                        "date": {"start": 1900, "end": "2026-05-01 21:00:00"},
                        "config": {"type": "Dining Room", "token": "rgs-bad-start"},
                        "size": {"min": 2, "max": 4},
                    },
                    # No `config` at all.
                    {
                        "date": {"start": "2026-05-01 18:00:00"},
                        "size": {"min": 2, "max": 4},
                    },
                    # `size` present but not a mapping.
                    {
                        "date": {"start": "2026-05-01 18:30:00"},
                        "config": {"type": "Bar", "token": "rgs-bad-size"},
                        "size": ["min", "max"],
                    },
                    # `date` present but not a mapping.
                    {
                        "date": "2026-05-01 18:45:00",
                        "config": {"type": "Bar", "token": "rgs-bad-date"},
                        "size": {"min": 2, "max": 4},
                    },
                    # The one good slot.
                    {
                        "date": {"start": "2026-05-01 20:00:00", "end": "2026-05-01 22:00:00"},
                        "config": {"type": "Dining Room", "token": "rgs-good-2000"},
                        "size": {"min": 2, "max": 4},
                    },
                ],
            }
        ]
    }
}

# Two slots that collapse onto ONE `Slot.slot_key` (`20:00|Bar`). The parser emits both; the
# diff engine resolves the collision last-parsed-wins and counts it in
# `DiffEngine.last_collision_count` (D-36). A parser that silently deduped here would hide the
# payload-shape surprise the counter exists to surface.
RESY_DUPLICATE_SLOT_RESPONSE: dict[str, Any] = {
    "results": {
        "venues": [
            {
                "venue": {"id": {"resy": RESY_FIXTURE_VENUE_ID}},
                "slots": [
                    {
                        "date": {"start": "2026-05-01 20:00:00", "end": "2026-05-01 22:00:00"},
                        "config": {"type": "Bar", "token": "rgs-first"},
                        "size": {"min": 2, "max": 2},
                    },
                    {
                        "date": {"start": "2026-05-01 20:00:00", "end": "2026-05-01 22:00:00"},
                        "config": {"type": "Bar", "token": "rgs-second"},
                        "size": {"min": 2, "max": 4},
                    },
                ],
            }
        ]
    }
}

# 429 rate-limit body. Never reaches `parse_resy` through a status-200 entry — the envelope
# entry carries `status: 429` and the parser skips it — but the adapter and the canary both
# need the shape.
#
# TODO(spike): capture the real 429 payload (it may be empty or HTML).
RESY_RATE_LIMIT_RESPONSE: dict[str, Any] = {
    "message": "Rate limit exceeded",
    "status": 429,
}

# The 403 soft-ban challenge body is HTML, NOT JSON — a `str`, not a `dict`. Calling `.json()`
# on it raises `JSONDecodeError` (reproduced in 03-RESEARCH.md §V5), which is exactly why the
# adapter must guard the decode and why this fixture is deliberately a different Python type
# from every other constant in this module.
#
# TODO(spike): capture the real Resy challenge page markup.
RESY_CHALLENGE_HTML: str = (
    "<!DOCTYPE html><html><head><title>Access Denied</title></head>"
    "<body><h1>Pardon the interruption</h1>"
    "<p>Please verify you are a human to continue.</p></body></html>"
)
