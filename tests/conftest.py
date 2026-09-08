"""Shared pytest fixtures for Mise en Place test suite."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

#: The one skip reason every browser test shows. It names the fix, because "Chromium not
#: installed" without `make browsers` sends the reader to the Playwright docs instead.
CHROMIUM_SKIP_REASON = (
    "Playwright Chromium for the pinned playwright version is not installed - run `make browsers`"
)


def _docker_available() -> bool:
    """Return True if a Docker-compatible runtime is reachable."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def kafka_container(request):
    if not _docker_available():
        pytest.skip("Docker not available")
    with KafkaContainer(image="confluentinc/cp-kafka:7.6.0") as kc:
        yield kc


@pytest.fixture(scope="module")
def redis_container(request):
    if not _docker_available():
        pytest.skip("Docker not available")
    with RedisContainer(image="redis:7.2-alpine") as rc:
        client = rc.get_client()
        client.config_set("maxmemory-policy", "noeviction")
        yield rc


@pytest.fixture(scope="module")
def timescale_container(request):
    if not _docker_available():
        pytest.skip("Docker not available")
    container = PostgresContainer(
        image="timescale/timescaledb:2.17.2-pg16",
        username="mise",
        password="mise",
        dbname="mise",
    )
    with container as tc:
        yield tc


def _pinned_chromium_revision() -> str:
    """
    The Chromium revision THIS `playwright` demands, read from its own driver manifest.

    Raises if the manifest is missing or malformed; `_chromium_available` is what turns that into
    a skip. Tests read the revision through this same function so a `playwright` bump cannot leave
    a hard-coded number behind in the test file.
    """
    import playwright

    manifest = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    browsers = json.loads(manifest.read_text())["browsers"]
    return str(next(b["revision"] for b in browsers if b["name"] == "chromium"))


def _playwright_browsers_root() -> Path:
    """
    Where Playwright looks for installed browsers, honouring `PLAYWRIGHT_BROWSERS_PATH`.

    Read from the environment on every call, never cached at import: a hard-coded per-platform
    root reports "not installed" on any CI image that relocates the cache, and the whole browser
    suite then skips green.
    """
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override == "0":
        # Playwright's documented "0" means: inside the package, not in a shared cache.
        import playwright

        return Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _chromium_available() -> bool:
    """
    True only when the EXACT revision the pinned playwright declares is on disk (B-1, D-71a).

    This compares revisions rather than globbing for "a chromium" for a reason that actually
    happened on this machine: the cache held `chromium-1223` from a newer Playwright while
    `playwright==1.58.0` pins 1208, so a glob-based guard reported "available" and every single
    `chromium.launch()` raised `Executable doesn't exist`. Nine browser tests would have failed
    with a stack trace instead of skipping with an instruction.

    Never raises. A guard that throws at collection time turns a missing browser into a suite-wide
    error, so any failure to answer the question is answered as "no" and the tests skip.
    """
    try:
        revision = _pinned_chromium_revision()
        return (_playwright_browsers_root() / f"chromium-{revision}").exists()
    except Exception:
        return False


@pytest.fixture
async def browser() -> AsyncIterator[Any]:
    """
    One headless Chromium for the duration of a single test (Pitfall 8: function scope is enough).

    `channel="chromium"` rather than the default headless shell: the shell leaks
    `HeadlessChrome` into `sec-ch-ua` client hints (Pitfall 2). Every context created from this
    browser must still pass an explicit `user_agent=`.

    The `finally` closes under `asyncio.shield` because a bare `await` in a `finally` reached
    through cancellation re-raises `CancelledError` at once and never closes the browser -
    research reproduced exactly that and counted six surviving Chromium processes (Pitfall 1).
    """
    if not _chromium_available():
        pytest.skip(CHROMIUM_SKIP_REASON)

    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    launched = await pw.chromium.launch(headless=True, channel="chromium")
    try:
        yield launched
    finally:
        await asyncio.shield(launched.close())
        await pw.stop()


def _free_port() -> int:
    """An ephemeral port the kernel just handed back, so parallel runs cannot collide."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def stub_base() -> AsyncIterator[str]:
    """
    The in-process Resy fake on `http://127.0.0.1:{ephemeral}` (D-71).

    Shutdown is driven by `server.should_exit` plus a BOUNDED wait, never by cancelling the serve
    task: uvicorn 0.44 restores the SIGINT/SIGTERM handlers it captured inside a context manager,
    and cancelling out from under that is how a test suite ends up unable to Ctrl-C. The
    pre-0.30 `install_signal_handlers = lambda: None` workaround is deliberately absent - it has
    no effect in the pinned version and reads as protection that is not there (Pitfall 9).
    """
    import uvicorn

    from tests.fakes.resy_stub import app, reset_stub

    reset_stub()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())

    async def _wait_started() -> None:
        # A bounded `for` rather than `while not server.started`: an unbounded poll loop that
        # never terminates is how a fixture failure becomes a hung suite instead of a red test.
        for _ in range(2_000):
            if server.started:
                return
            await asyncio.sleep(0.01)
        raise RuntimeError("uvicorn stub never reported started")

    await asyncio.wait_for(_wait_started(), timeout=10)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=10)
        reset_stub()
