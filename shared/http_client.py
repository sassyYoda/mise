"""Shared httpx.AsyncClient singleton. One client per process — Pitfall 9.

Process-wide singleton factory: the first caller to :func:`get_async_client`
constructs a single :class:`httpx.AsyncClient` configured with the module-level
:data:`LIMITS` and :data:`TIMEOUT` constants; every subsequent caller receives
the same instance. :func:`close_async_client` is idempotent so lifespan code
can call it unconditionally on shutdown.

Do NOT construct :class:`httpx.AsyncClient` anywhere else in the codebase.
Pitfall 9 in PITFALLS.md documents the FD leak caused by per-poll clients.
"""
from __future__ import annotations

import httpx

_client: httpx.AsyncClient | None = None

# Public module constants so callers can assert the expected values in tests
# and so the poller main.py can reference them in log lines.
LIMITS: httpx.Limits = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
)
TIMEOUT: httpx.Timeout = httpx.Timeout(10.0, connect=5.0)


def get_async_client() -> httpx.AsyncClient:
    """Return the process-wide :class:`httpx.AsyncClient`.

    Constructs the client on first call; subsequent calls return the same
    instance. Thread-safety note: callers are expected to use asyncio
    single-threaded event loop model — no locking needed.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(limits=LIMITS, timeout=TIMEOUT)
    return _client


async def close_async_client() -> None:
    """Close the singleton client at shutdown. Safe to call multiple times."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
