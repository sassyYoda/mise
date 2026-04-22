#!/usr/bin/env python
"""
SC5 / PERF-02: Assert >= 99% poll success rate in every hourly bucket over last 24h.
Queries poll_log TimescaleDB hypertable using time_bucket() (D-11).

Usage: uv run python scripts/check_poll_success.py
Or:    make verify-perf02

Exit codes:
  0 — All hourly buckets have success_rate >= 0.99 (PERF-02 passed)
  1 — One or more buckets are below 0.99 (PERF-02 failed)
  2 — Not enough data (fewer than 24 hourly buckets — run has not completed 24h yet)
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any

import asyncpg

DATABASE_URL_ASYNC = os.getenv(
    "DATABASE_URL_ASYNC",
    "postgresql+asyncpg://mise:mise@localhost:5432/mise",
)

# PERF-02 success threshold
SUCCESS_RATE_THRESHOLD = 0.99

# Minimum hours of data required to claim PERF-02 (24h window)
REQUIRED_HOURS = 24


@dataclass
class HourlyBucket:
    hour: Any  # datetime
    total: int
    success: int

    @property
    def rate(self) -> float:
        return self.success / self.total if self.total > 0 else 0.0


async def check() -> int:
    """
    Run PERF-02 check. Returns exit code (0=pass, 1=fail, 2=insufficient data).
    """
    # Strip asyncpg prefix if set; asyncpg uses postgresql:// not postgresql+asyncpg://
    url = DATABASE_URL_ASYNC.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            """
            SELECT
                time_bucket('1 hour', time)           AS hour,
                COUNT(*)                               AS total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success
            FROM poll_log
            WHERE time >= NOW() - INTERVAL '24 hours'
            GROUP BY hour
            ORDER BY hour
            """
        )
    finally:
        await conn.close()

    if not rows:
        print("ERROR: No data in poll_log for the last 24 hours.", file=sys.stderr)
        print("Ensure the poller has been running for at least 1 hour.", file=sys.stderr)
        return 2

    buckets = [
        HourlyBucket(
            hour=row["hour"],
            total=int(row["total"]),
            success=int(row["success"]),
        )
        for row in rows
    ]

    # Print per-hour table
    print(f"{'Hour (UTC)':<25} {'Total':>8} {'Success':>8} {'Rate':>8} {'Status':>8}")
    print("-" * 62)

    failing_hours: list[HourlyBucket] = []
    for b in buckets:
        status = "PASS" if b.rate >= SUCCESS_RATE_THRESHOLD else "FAIL"
        if b.rate < SUCCESS_RATE_THRESHOLD:
            failing_hours.append(b)
        print(f"{str(b.hour):<25} {b.total:>8} {b.success:>8} {b.rate:>8.4f} {status:>8}")

    print("-" * 62)
    print(f"Total hours with data: {len(buckets)}")

    if len(buckets) < REQUIRED_HOURS:
        print(
            f"\nWARNING: Only {len(buckets)} hourly buckets found (need {REQUIRED_HOURS} for PERF-02).",
            file=sys.stderr,
        )
        print(
            "PERF-02: INSUFFICIENT DATA — run has not completed 24h yet.",
            file=sys.stderr,
        )
        return 2

    if failing_hours:
        print(
            f"\nPERF-02 FAILED: {len(failing_hours)} hourly bucket(s) below "
            f"{SUCCESS_RATE_THRESHOLD:.0%}:"
        )
        for b in failing_hours:
            print(f"  {b.hour}: {b.rate:.4f} ({b.success}/{b.total})")
        return 1

    print(
        f"\nPERF-02 PASSED: All {len(buckets)} hourly buckets >= "
        f"{SUCCESS_RATE_THRESHOLD:.0%} success rate."
    )
    return 0


def main() -> None:
    exit_code = asyncio.run(check())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
