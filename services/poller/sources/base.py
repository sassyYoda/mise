"""Abstract base class for availability polling sources (D-19)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class AvailabilitySource(ABC):
    """Abstract polling source.

    Concrete implementations: :class:`OpenTableAdapter` (P1),
    :class:`ResyAdapter` (P3). Each source receives a shared
    :class:`httpx.AsyncClient` at construction — NEVER creates its own
    (Pitfall 9).
    """

    @abstractmethod
    async def poll(
        self,
        rid: int,
        dates: list[date],
        party_sizes: list[int],
    ) -> dict[str, Any]:
        """Poll availability for a restaurant.

        Args:
            rid: Platform-specific restaurant ID.
            dates: Dates to poll.
            party_sizes: Party sizes to poll.

        Returns:
            The full raw response dict. Must contain the complete raw API
            response for the ``availability.raw`` Kafka payload so that
            Phase 2 differ can replay from scratch (D-19).
        """
        ...
