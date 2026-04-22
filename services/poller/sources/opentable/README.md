# OpenTable Adapter — DevTools Spike Findings

<!-- SPIKE STATUS: PLACEHOLDER — needs live browser confirmation -->

This document captures the result of the 30-minute DevTools spike that confirms
the OpenTable widget availability endpoint currently in use. Sections below
populated from 01-RESEARCH.md §4 with **`[ASSUMED]`** markers — update every
field after running the procedure described in `01-05-PLAN.md` Task 1 against
a live NYC restaurant page (e.g. https://www.opentable.com/r/carbone-new-york).

The adapter code (`adapter.py`, `graphql.py`, `fixtures.py`) is fully testable
against respx mocks using the values below, so Wave-4 integration tests pass
today. Once a human completes the spike, only two files need editing:

- `graphql.py`: `OPENTABLE_GQL_ENDPOINT`, `OPENTABLE_HEADERS`, the GraphQL
  `query` string, and the `variables` shape inside `build_request()`.
- `fixtures.py`: the JSON bodies in `OPENTABLE_SUCCESS_RESPONSE` /
  `OPENTABLE_EMPTY_RESPONSE` so they match live response shape.

Once updated, rerun `uv run pytest tests/integration/test_poller_smoke.py` to
validate end-to-end.

---

## Endpoint

**Status:** `[ASSUMED]` per 01-RESEARCH.md §4 — awaiting live DevTools capture.

<!-- TODO(spike): confirm via DevTools capture on a live OT restaurant page -->

Primary candidate (tried first by adapter):

```
POST https://www.opentable.com/dapi/fe/gql/prod
```

Secondary candidate (REST fallback if GraphQL is gated):

```
GET  https://www.opentable.com/restref/api/availability?rid={rid}&...
```

Tertiary candidate (HTML fallback if both are gated):

```
GET  https://www.opentable.com/widget/reservation/canvas?rid={rid}&datetime={...}&partysize={...}
```

## Headers

**Status:** `[ASSUMED]` — confirm exact casing and presence via DevTools.

<!-- TODO(spike): copy the exact header block from the DevTools request -->

| Header | Value | Source |
|---|---|---|
| `User-Agent` | rotating per request from `services/poller/config.USER_AGENTS` (≥4 real browser UAs) | T-03 mitigation |
| `Accept` | `application/json` | RESEARCH §4 |
| `Content-Type` | `application/json` | RESEARCH §4 |
| `Origin` | `https://www.opentable.com` | RESEARCH §4 |
| `Referer` | `https://www.opentable.com/r/{slug}` | RESEARCH §4 |

Cookies: spike must verify whether the endpoint is reachable in an incognito
tab **without** session cookies. If cookies required → switch to `option-c`
(HTML fallback via `__NEXT_DATA__`) documented in the Decision section.

## Query Shape

**Status:** `[ASSUMED]` GraphQL POST body. Shape is tracked in
`services/poller/sources/opentable/graphql.py::build_request()`.

<!-- TODO(spike): replace with exact operationName / query string captured live -->

```jsonc
{
  "operationName": "RestaurantsAvailability",
  "variables": {
    "restaurantIds": [12345],
    "partySize": 2,
    "startDate": "2026-05-01",
    "endDate": "2026-05-07",
    "databaseRegion": "NA"
  },
  "query": "query RestaurantsAvailability($restaurantIds: [Int!]!, $partySize: Int!, $startDate: String!, $endDate: String!, $databaseRegion: String!) { availability(restaurantIds: $restaurantIds, partySize: $partySize, startDate: $startDate, endDate: $endDate, databaseRegion: $databaseRegion) { restaurantId availability { date timeSlots { time seatingTypes token } } } }"
}
```

Response (typical): `data.availability[].availability[].timeSlots[].{time, seatingTypes, token}`.

## Rate-Limit Observations

**Status:** `[ASSUMED]` — confirm during spike by hammering the endpoint once
from a non-residential IP.

<!-- TODO(spike): record any Retry-After / X-RateLimit-* headers observed -->

- RESEARCH §4: community scrapers report ~1 req/sec per restaurant tolerated.
- P1 global throughput = 50 restaurants × 1 poll / 90s ≈ 0.55 req/sec — well
  under any reasonable cap.
- Adapter respects `Retry-After` on HTTP 429 (see `adapter.py::_fetch`): sleeps
  for the duration specified, then re-raises as transient for tenacity retry.
- Scheduler jitters the poll interval ±15% (D-17) to prevent constant-interval
  fingerprinting (T-03 mitigation).

## Decision: GraphQL | HTML Fallback

**Status:** `[ASSUMED — option-a pending spike]`

<!-- TODO(spike): after DevTools capture, type one of:
     "approved: option-a"   GraphQL confirmed — keep graphql.py POST as-is
     "approved: option-b"   REST confirmed — change graphql.py to GET with query params
     "approved: option-c"   endpoint gated — rewrite adapter to fetch HTML + parse __NEXT_DATA__
-->

**Current decision (placeholder):** `option-a` — GraphQL POST to
`https://www.opentable.com/dapi/fe/gql/prod`.

Rationale for the placeholder: the research file (01-RESEARCH §4) documents
this as the canonical path with MEDIUM confidence; community scrapers
(nfmcclure/opentable_availability_check, jonluca/OpenTable bot) confirm it
works without cookies as of 2025. The fallback paths are documented above so
the spike operator can flip a single variable (`OPENTABLE_GQL_ENDPOINT`) if
they find otherwise.

**Adapter behavior already handles all three options:** `adapter.py::_fetch`
issues a POST with JSON body + rotating UA + tenacity retry, and the query
builder (`graphql.py::build_request`) returns the body. If the spike confirms
option-b (REST GET), swap `build_request()` to return a query params dict and
change `_fetch` to `self.client.get(endpoint, params=params, headers=headers)`.
If option-c (HTML), replace `_fetch` body with an HTML fetch + `__NEXT_DATA__`
JSON extraction — the rest of the pipeline (publisher, scheduler, poll_log)
does not change because the response is still stored verbatim in
`availability.raw` for Phase 2 replay.
