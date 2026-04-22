"""
Golden-file JSON fixtures for OpenTable adapter unit/integration tests.
Used with respx to mock the OpenTable endpoint without real network calls (D-34).

Shapes are [ASSUMED] per 01-RESEARCH.md §4 — update from
services/poller/sources/opentable/README.md ## Query Shape after the
DevTools spike confirms the live response schema.
"""
from __future__ import annotations

from typing import Any

# Minimal success response — 1 restaurant, 1 date, 1 timeslot.
# TODO(spike): confirm exact JSON structure against a live OpenTable response.
OPENTABLE_SUCCESS_RESPONSE: dict[str, Any] = {
    "data": {
        "availability": [
            {
                "restaurantId": 42,
                "availability": [
                    {
                        "date": "2026-05-01",
                        "timeSlots": [
                            {
                                "time": "19:00",
                                "seatingTypes": ["bar", "standard"],
                                "token": "abc123-reservation-token",
                            }
                        ],
                    }
                ],
            }
        ]
    }
}

# Empty availability — no slots (restaurant fully booked).
# TODO(spike): confirm OpenTable returns empty `availability` array vs null.
OPENTABLE_EMPTY_RESPONSE: dict[str, Any] = {
    "data": {
        "availability": [
            {
                "restaurantId": 42,
                "availability": [],
            }
        ]
    }
}

# 429 rate limit response body.
# TODO(spike): capture the real 429 payload shape if possible (may just be empty).
OPENTABLE_RATE_LIMIT_RESPONSE: dict[str, Any] = {
    "errors": [
        {
            "message": "Too many requests",
            "extensions": {"code": "RATE_LIMITED"},
        }
    ]
}
