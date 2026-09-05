"""Unit: WR-02 — SIGTERM must unwind the exit stack, not terminate the process.

A grep for SIGTERM or add_signal_handler across services/ and shared/ used to return one hit,
and it was a comment explaining why the CRASH hook uses SIGKILL. Neither service handled the
signal that `docker stop`, `make down`, a Kubernetes eviction and `Popen.terminate()` all
send, so the `AsyncExitStack` WR-04 built and the `dispose_engine()` WR-05 registered never
ran on the only shutdown path that actually happens.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from shared.shutdown import run_until_signal

REPO_ROOT = Path(__file__).resolve().parents[2]

unix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="add_signal_handler is a Unix event-loop feature"
)


@pytest.mark.asyncio
async def test_a_service_that_returns_on_its_own_is_awaited_normally() -> None:
    done: list[str] = []

    async def service() -> None:
        done.append("ran")

    await run_until_signal(service())

    assert done == ["ran"]


@pytest.mark.asyncio
async def test_a_crashing_service_still_fails_loudly() -> None:
    """Cancellation on signal must not swallow a genuine crash."""

    async def service() -> None:
        raise RuntimeError("kafka is gone")

    with pytest.raises(RuntimeError, match="kafka is gone"):
        await run_until_signal(service())


@unix_only
@pytest.mark.asyncio
async def test_sigterm_cancels_the_service_so_its_teardown_runs() -> None:
    """The whole point: the `finally` that closes the consumer/producer/Redis must execute."""
    started = asyncio.Event()
    torn_down: list[str] = []

    async def service() -> None:
        started.set()
        try:
            await asyncio.Event().wait()  # the real loop never returns either
        finally:
            torn_down.append("closed")

    async def send_sigterm() -> None:
        await started.wait()
        os.kill(os.getpid(), signal.SIGTERM)

    await asyncio.wait_for(
        asyncio.gather(run_until_signal(service()), send_sigterm()), timeout=10
    )

    assert torn_down == ["closed"], (
        "SIGTERM did not reach the service as cancellation, so nothing was torn down"
    )


@unix_only
@pytest.mark.asyncio
async def test_the_signal_handlers_are_removed_again() -> None:
    """A handler left installed would hijack SIGINT for every later test in the session."""
    loop = asyncio.get_running_loop()

    async def service() -> None:
        return None

    await run_until_signal(service())

    # remove_signal_handler returns False when nothing was installed for that signal.
    assert loop.remove_signal_handler(signal.SIGTERM) is False
    assert loop.remove_signal_handler(signal.SIGINT) is False


@pytest.mark.asyncio
async def test_cancelling_the_caller_leaves_no_orphan_task() -> None:
    """An outer cancel (what the e2e test does) must not leave the service running."""
    started = asyncio.Event()
    torn_down: list[str] = []

    async def service() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            torn_down.append("closed")

    task = asyncio.create_task(run_until_signal(service()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert torn_down == ["closed"]


@pytest.mark.parametrize(
    "entry_point",
    ["services/state_machine/main.py", "services/poller/main.py"],
)
def test_both_entry_points_install_the_shutdown_handler(entry_point: str) -> None:
    """A service that stops calling this silently loses its teardown again."""
    source = (REPO_ROOT / entry_point).read_text()
    assert "run_until_signal(" in source, (
        f"{entry_point} no longer awaits run_until_signal, so SIGTERM kills it outright"
    )
