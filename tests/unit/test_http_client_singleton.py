"""Unit tests for shared.http_client singleton (Pitfall 9). Filled by Plan 05."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — shared.http_client singleton implemented in Plan 05")
def test_get_async_client_returns_singleton():
    """Subsequent calls to get_async_client() must return the same httpx.AsyncClient instance."""
    pass


@pytest.mark.skip(reason="Wave-0 stub — shared.http_client singleton implemented in Plan 05")
def test_client_limits_configured():
    """Shared client exposes Limits(max_connections=100, max_keepalive_connections=20)."""
    pass
