"""OpenTable availability polling adapter (D-05, D-19, POLL-03).

Uses the shared ``httpx.AsyncClient`` singleton — NEVER creates per-poll
clients (Pitfall 9). Implements tenacity retry with ``Retry-After`` header
support (T-03 mitigation).
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, cast

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from services.poller.config import random_user_agent
from services.poller.sources.base import AvailabilitySource
from services.poller.sources.opentable.graphql import (
    OPENTABLE_GQL_ENDPOINT,
    OPENTABLE_HEADERS,
    build_request,
)
from shared.telemetry import get_logger

log = get_logger(__name__)

# Transient exception classes that tenacity should retry.
_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


class OpenTableAdapter(AvailabilitySource):
    """Polls the OpenTable widget GraphQL endpoint for restaurant availability.

    Created once per process with a shared :class:`httpx.AsyncClient` (D-05).
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client  # shared, NEVER per-poll (D-05, Pitfall 9)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8, jitter=2),
        retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS + (httpx.HTTPStatusError,)),
        before_sleep=before_sleep_log(log, 30),  # WARNING = 30
        reraise=True,
    )
    async def _fetch(
        self,
        rid: int,
        dates: list[date],
        party_sizes: list[int],
    ) -> dict[str, Any]:
        headers = {**OPENTABLE_HEADERS, "User-Agent": random_user_agent()}
        resp = await self.client.post(
            OPENTABLE_GQL_ENDPOINT,
            json=build_request(rid, dates, party_sizes),
            headers=headers,
        )
        if resp.status_code == 429:
            retry_after_raw = resp.headers.get("Retry-After", "5")
            try:
                retry_after = int(retry_after_raw)
            except ValueError:
                retry_after = 5
            log.warning(
                "opentable_rate_limited",
                rid=rid,
                retry_after=retry_after,
            )
            await asyncio.sleep(retry_after)
            # Re-raise as transient so tenacity schedules another attempt.
            raise httpx.ReadTimeout(
                "429 rate limited — retry after sleep",
                request=resp.request,
            )
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())

    async def poll(
        self,
        rid: int,
        dates: list[date],
        party_sizes: list[int],
    ) -> dict[str, Any]:
        """Poll OpenTable for availability.

        Returns the full raw response dict so it can be stored verbatim in
        the ``availability.raw`` Kafka message for Phase 2 replay (D-19).
        """
        return await self._fetch(rid, dates, party_sizes)
