"""
SQLAlchemy 2.0 async ORM models and session factory (D-04).
Uses asyncpg driver for app hot path; psycopg3 is for Alembic only.
Named tables: users, restaurants, watchlist_entries, notification_log,
              availability_events, poll_log
Named symbols: get_engine, get_async_session, dispose_engine
"""
from __future__ import annotations

import os
from datetime import date, datetime
from datetime import time as dt_time
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # BYTEA, AES-256-GCM (D-32, T-04)
    phone: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)          # 'opentable' | 'resy'
    platform_id: Mapped[str] = mapped_column(Text, nullable=False)     # stringified OT rid or Resy venue_id
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # NOT unique on its own since migration 0009 (D-63b): a slug identifies a
    # RESTAURANT, not a row, so one logical restaurant holds one row per source under
    # one slug. Uniqueness is the composite (slug, source) in __table_args__ below.
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    neighborhood: Mapped[str] = mapped_column(Text, nullable=False)
    cuisine: Mapped[str] = mapped_column(Text, nullable=False)
    price_tier: Mapped[int] = mapped_column(Integer, nullable=False)   # CHECK 1..4 enforced in migration
    cover_photo_url: Mapped[str] = mapped_column(Text, nullable=False)
    date_range_days: Mapped[int] = mapped_column(Integer, server_default="7", nullable=False)
    party_sizes: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=sa_text("'{2,4}'::integer[]"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("source", "platform_id", name="uq_restaurants_source_platform_id"),
        # Migration 0009 (D-63b). The upsert and join key is still (source, platform_id)
        # (D-52); this constraint only stops the SAME source claiming one slug twice.
        UniqueConstraint("slug", "source", name="uq_restaurants_slug_source"),
    )


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("restaurants.id"), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    time_window_from: Mapped[dt_time | None] = mapped_column(Time, nullable=True)
    time_window_to: Mapped[dt_time | None] = mapped_column(Time, nullable=True)
    days_of_week: Mapped[str | None] = mapped_column(Text, nullable=True)
    seat_type_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    channels: Mapped[str] = mapped_column(Text, server_default="email", nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="active", nullable=False)
    management_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watch_id: Mapped[int] = mapped_column(Integer, ForeignKey("watchlist_entries.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    slot_still_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


# Note: availability_events and poll_log are TimescaleDB hypertables created via
# Alembic migrations (0006, 0007) — not via SQLAlchemy create_all.
# ORM classes below are for querying only; never use Base.metadata.create_all() for these.

class AvailabilityEvent(Base):
    """One confirmed availability event.

    Primary key is ``(time, event_id)`` and matches migration 0008's unique index —
    ``restaurant_id`` is deliberately NOT part of it, because every slot confirmed by
    one poll shares that poll's ``time`` and a ``(time, restaurant_id)`` key collides
    on the second slot (research B-3). Close by ``WHERE event_id = :event_id AND
    "time" = :confirmed_at`` for a single-chunk index scan.
    """

    __tablename__ = "availability_events"
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)
    # D-52: the SOURCE PLATFORM id (OpenTable rid / Resy venue id), as poll_log.restaurant_id
    # already is — NOT restaurants.id. Join key against restaurants is (source, platform_id).
    restaurant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    time_slot: Mapped[dt_time | None] = mapped_column(Time, nullable=True)
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seat_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hours_before_service: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PollLog(Base):
    __tablename__ = "poll_log"
    # Named Symbol columns verbatim (D-31, REQUIREMENTS.md poll_log columns)
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)   # 'success' | 'error' | 'timeout'
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the async SQLAlchemy engine. Creates it on first call."""
    global _engine
    if _engine is None:
        url = os.getenv(
            "DATABASE_URL_ASYNC",
            "postgresql+asyncpg://mise:mise@localhost:5432/mise",
        )
        _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory. Creates it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def dispose_engine() -> None:
    """
    Close the engine's connection pool and drop the cached singletons.

    Every long-running service must await this on shutdown. Without it the asyncpg pool's
    connections are garbage-collected against a closing event loop, which produces
    "Event loop is closed" / unclosed-connection noise and leaves server-side sessions to time
    out on their own. Safe to call when no engine was ever created, and safe to call twice.
    """
    global _engine, _session_factory
    engine, _engine, _session_factory = _engine, None, None
    if engine is not None:
        await engine.dispose()
