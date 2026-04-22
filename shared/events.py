"""
Pydantic v2 Kafka message schemas.
Single source of truth for all Kafka message contracts (D-06).
Named symbols: AvailabilityRaw, PollCompleted
"""
from __future__ import annotations
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AvailabilityRaw(BaseModel):
    """Emitted to availability.raw for each completed OpenTable or Resy poll."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    polled_at_epoch_ms: int
    raw_response: dict[str, Any]
    request_params: dict[str, Any]

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


class PollCompleted(BaseModel):
    """Emitted to polls.completed after each poll attempt."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    polled_at_epoch_ms: int
    status: Literal["success", "error", "timeout"]
    latency_ms: int
    http_status: int | None = None
    error: str | None = None

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")
