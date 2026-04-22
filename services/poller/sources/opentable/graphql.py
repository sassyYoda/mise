"""OpenTable availability request builder.

Update :data:`OPENTABLE_GQL_ENDPOINT` and :func:`build_request` if OpenTable
changes its schema. All endpoint details are documented in
``services/poller/sources/opentable/README.md``. Values here are ``[ASSUMED]``
placeholders drawn from 01-RESEARCH §4 — confirm via DevTools spike.
"""
from __future__ import annotations

from datetime import date
from typing import Any

# UPDATE after spike confirms endpoint (see README.md ## Endpoint).
OPENTABLE_GQL_ENDPOINT: str = "https://www.opentable.com/dapi/fe/gql/prod"

# Headers required by OpenTable widget requests (see README.md ## Headers).
# User-Agent is injected per-request by the adapter from USER_AGENTS (T-03).
OPENTABLE_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.opentable.com",
}


def build_request(
    rid: int,
    target_dates: list[date],
    party_sizes: list[int],
) -> dict[str, Any]:
    """Build the POST body for OpenTable availability GraphQL query.

    If the DevTools spike confirms a REST endpoint, change this to return
    the query-params dict instead and update :func:`adapter._fetch` to use
    ``self.client.get(endpoint, params=...)``.
    """
    # NOTE: Update query name and variables shape from README.md ## Query Shape
    # once the live DevTools spike is complete.
    if not target_dates:
        raise ValueError("build_request: target_dates must be non-empty")
    if not party_sizes:
        raise ValueError("build_request: party_sizes must be non-empty")

    return {
        "operationName": "RestaurantsAvailability",
        "variables": {
            "restaurantIds": [rid],
            "partySize": party_sizes[0],  # Primary party size; adapter loops for multiple
            "startDate": target_dates[0].isoformat(),
            "endDate": target_dates[-1].isoformat(),
            "databaseRegion": "NA",
        },
        "query": (
            "query RestaurantsAvailability($restaurantIds: [Int!]!, "
            "$partySize: Int!, $startDate: String!, $endDate: String!, "
            "$databaseRegion: String!) {\n"
            "  availability(\n"
            "    restaurantIds: $restaurantIds\n"
            "    partySize: $partySize\n"
            "    startDate: $startDate\n"
            "    endDate: $endDate\n"
            "    databaseRegion: $databaseRegion\n"
            "  ) {\n"
            "    restaurantId\n"
            "    availability {\n"
            "      date\n"
            "      timeSlots {\n"
            "        time\n"
            "        seatingTypes\n"
            "        token\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        ),
    }
