"""
Cooperative shutdown for long-running service entry points (WR-02).

Every service in this repo builds its resources on an ``AsyncExitStack`` (or a ``finally``)
and then awaits a loop that never returns. Nothing handled SIGTERM, so on the only shutdown
path that actually happens in production — ``docker stop``, ``make down``, a Kubernetes
eviction, a ``Popen.terminate()`` — Python's default disposition killed the process outright
and NONE of that teardown ran: no ``consumer.stop()``, no ``producer.stop()`` (dropping the
in-flight batch the 20 ms linger window is holding), no ``r.aclose()``, no
``dispose_engine()``. ``shared/db.py`` states "Every long-running service must await this on
shutdown", which was a requirement the services structurally could not meet.

``run_until_signal`` turns the signal into task cancellation, which unwinds the stack the
ordinary way. SIGKILL remains uncatchable, which is exactly why the chaos hook uses it.

Named symbols: run_until_signal
"""
from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable
from contextlib import suppress
from typing import Any

from shared.telemetry import get_logger

log = get_logger(__name__)

SHUTDOWN_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)


async def run_until_signal(main: Awaitable[object]) -> None:
    """
    Await ``main`` until it returns, raises, or a shutdown signal arrives.

    On a signal the coroutine is CANCELLED rather than the process being torn down, so the
    caller's ``async with AsyncExitStack()`` / ``finally`` runs normally. Whatever ``main``
    raises on its own is re-raised unchanged, so a genuine crash still fails loudly.

    ``add_signal_handler`` is only available on a Unix event loop in the main thread; both
    other cases (Windows, a loop on a worker thread — the shape an integration test that
    drives ``run()`` as a task can produce) raise, and are handled by simply not installing
    the handler. That degrades to the previous behaviour rather than refusing to start.
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    installed: list[signal.Signals] = []
    for sig in SHUTDOWN_SIGNALS:
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):  # pragma: no cover
            continue
        installed.append(sig)

    # ensure_future, not create_task: the poller hands in an `asyncio.gather(...)` future
    # rather than a bare coroutine, and cancelling that future cancels its children.
    runner: asyncio.Future[Any] = asyncio.ensure_future(main)
    waiter: asyncio.Future[Any] = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if runner.done():
            await runner  # re-raise whatever ended it
            return
        log.info("shutdown_signal_received")
    finally:
        waiter.cancel()
        with suppress(asyncio.CancelledError):
            await waiter
        if not runner.done():
            # Also the path taken when the CALLER is cancelled: the inner task must never be
            # left running against resources the exit stack is about to close.
            runner.cancel()
            with suppress(asyncio.CancelledError):
                await runner
        for sig in installed:
            with suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(sig)
