"""Allow ``python -m services.state_machine`` (D-08, Makefile ``make state-machine`` target)."""
from __future__ import annotations

import asyncio

from services.state_machine.main import run

asyncio.run(run())
