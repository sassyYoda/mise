"""Allow ``python -m services.poller`` (D-08, Makefile ``make poll`` target)."""
from __future__ import annotations

import asyncio

from services.poller.main import run

asyncio.run(run())
