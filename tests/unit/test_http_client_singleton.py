"""Unit tests for :mod:`shared.http_client` singleton (Pitfall 9)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from shared import http_client


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure a clean singleton across tests."""
    asyncio.run(http_client.close_async_client())
    yield
    asyncio.run(http_client.close_async_client())


def test_get_async_client_returns_singleton():
    a = http_client.get_async_client()
    b = http_client.get_async_client()
    assert a is b
    assert isinstance(a, httpx.AsyncClient)


def test_client_limits_configured():
    # httpx stores limits on the transport/pool; assert the module-level
    # constants which are what consumer code references.
    http_client.get_async_client()
    assert http_client.LIMITS.max_connections == 100
    assert http_client.LIMITS.max_keepalive_connections == 20


def test_close_async_client_is_idempotent():
    # Close once (no client exists) — should not raise.
    asyncio.run(http_client.close_async_client())
    asyncio.run(http_client.close_async_client())

    # Create and close — should reset internal state so the next
    # get_async_client() builds a fresh instance.
    c1 = http_client.get_async_client()
    asyncio.run(http_client.close_async_client())
    c2 = http_client.get_async_client()
    assert c1 is not c2
