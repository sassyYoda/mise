"""
In-process Resy fake — the ONLY origin any browser test in this phase is allowed to reach (D-71).

No test in this repository resolves or contacts a `resy.com` host. Every Playwright test, the
adapter tests and the soak script point `RESY_API_BASE` at this app running on `127.0.0.1` on an
ephemeral port, so "did we accidentally poll production while iterating on a test?" is a question
with a structural answer rather than a careful one.

The five modes are the five responses research actually observed for `/4/find`, with their exact
statuses AND content types (03-RESEARCH.md "The `/4/find` call and its error taxonomy"):

    normal          200  application/json   the success body
    rate_limited    429  application/json   + `Retry-After: 30`
    banned_empty    200  application/json   `venues: []` — Pitfall 10: indistinguishable from a
                                            genuinely fully-booked night at parse time, which is
                                            the entire reason the POLL-06 canary exists
    challenge_403   403  text/html          the soft-ban challenge page; `.json()` on it raises
    error_500       500  text/plain

The content type is part of the contract, not a detail: `APIResponse.json()` raises
`JSONDecodeError` on the 403 challenge page, and an adapter that forgot to guard the decode fails
here rather than in production.

The hit log records the client-facing requests only — `/__ctl/*` is the test harness talking to
itself, and counting those would make "how many polls did the adapter make?" an unanswerable
question. Headers are recorded in full because that is how B-9's explicit `extra_http_headers`
(Accept-Language, sec-ch-ua*, Sec-Fetch-*) are proven to reach the wire.

Named symbols: MODES, Mode, app, reset_stub, current_mode, hits
"""
from __future__ import annotations

from typing import Any, Literal, get_args

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from services.poller.sources.resy.fixtures import (
    RESY_CHALLENGE_HTML,
    RESY_EMPTY_VENUES_RESPONSE,
    RESY_RATE_LIMIT_RESPONSE,
    RESY_SUCCESS_RESPONSE,
)

Mode = Literal["normal", "rate_limited", "banned_empty", "challenge_403", "error_500"]

#: Every accepted mode. Derived from the Literal so the two can never drift apart.
MODES: tuple[str, ...] = get_args(Mode)

_ERROR_500_BODY = "internal error"

_mode: Mode = "normal"
_hits: list[dict[str, Any]] = []

app = FastAPI(title="resy-stub")


class _ModeRequest(BaseModel):
    """`POST /__ctl/mode` body. An unknown mode is a 422 — a silent no-op would fake a green test."""

    mode: Mode


def reset_stub() -> None:
    """Return the stub to `normal` with an empty hit log. Call between tests, not between requests."""
    global _mode
    _mode = "normal"
    _hits.clear()


def current_mode() -> Mode:
    """The mode the next `/4/find` will answer in."""
    return _mode


def hits() -> list[dict[str, Any]]:
    """A copy of the hit log, oldest first."""
    return list(_hits)


@app.middleware("http")
async def _record_hit(request: Request, call_next: Any) -> Response:
    """Log every client-facing request's path, query and FULL header mapping before serving it."""
    if not request.url.path.startswith("/__ctl"):
        _hits.append(
            {
                "path": request.url.path,
                "query": dict(request.query_params),
                "headers": dict(request.headers),
            }
        )
    response: Response = await call_next(request)
    return response


@app.get("/")
async def index() -> HTMLResponse:
    """
    A real HTML document on a real origin — the page the stealth tests navigate to.

    They must never assert against `about:blank`: there `navigator.userAgent.js` throws and
    silently disables every later patch including `webdriver` (03-RESEARCH.md Pitfall 3), so the
    assertions would pass on a context whose stealth never applied.
    """
    return HTMLResponse("<!doctype html><html><head><title>resy stub</title></head><body></body></html>")


@app.get("/4/find")
async def find() -> Response:
    """The availability endpoint, answering in whichever mode `POST /__ctl/mode` last selected."""
    if _mode == "normal":
        return JSONResponse(RESY_SUCCESS_RESPONSE)
    if _mode == "banned_empty":
        return JSONResponse(RESY_EMPTY_VENUES_RESPONSE)
    if _mode == "rate_limited":
        return JSONResponse(
            RESY_RATE_LIMIT_RESPONSE, status_code=429, headers={"Retry-After": "30"}
        )
    if _mode == "challenge_403":
        return HTMLResponse(RESY_CHALLENGE_HTML, status_code=403)
    return PlainTextResponse(_ERROR_500_BODY, status_code=500)


@app.post("/__ctl/mode")
async def set_mode(body: _ModeRequest) -> dict[str, str]:
    """Switch response mode. Returns the mode now in force."""
    global _mode
    _mode = body.mode
    return {"mode": _mode}


@app.get("/__ctl/hits")
async def get_hits() -> list[dict[str, Any]]:
    """Every client-facing request seen since the last clear, oldest first."""
    return hits()


@app.delete("/__ctl/hits", status_code=204)
async def clear_hits() -> None:
    """Empty the hit log. Leaves the mode alone — `POST /__ctl/mode` owns that."""
    _hits.clear()
