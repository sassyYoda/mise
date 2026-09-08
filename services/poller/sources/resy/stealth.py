"""
Per-CONTEXT stealth built from OUR fingerprint (POLL-04, D-60a, corrects D-60 per B-2/B-3).

Two things this module deliberately does NOT do. Both were measured, not guessed, and both look
like obvious "fixes" to a reader who has not read the transcripts:

1. It never calls `playwright_stealth.stealth_async`. That function takes a **Page**, not a
   BrowserContext, and does not propagate: research applied it to a page and a sibling page created
   afterwards in the SAME context still reported `navigator.webdriver === true`
   (03-RESEARCH.md B-2). Worse, it regenerates a RANDOM `Properties()` on every call — three
   consecutive calls produced a Qualcomm Adreno GPU, a Mirandese `navigator.languages`, and a
   `Chrome/96.0.4664.45` build from 2021 — and writes that identity over the context's real one
   while the HTTP `User-Agent` header keeps saying macOS Chrome 140 (B-3). Applied as shipped it
   makes the fleet MORE detectable than doing nothing.

2. It never passes fingerprint values through `StealthConfig`. `StealthConfig.vendor`, `.renderer`,
   `.nav_user_agent`, `.nav_platform`, `.languages` and `.nav_vendor` are DEAD in 1.2.0 — every
   shipped script reads `opts.*`, and `_stealth_config.py` references none of those attributes
   (B-3, verified by grep). Setting them changes nothing and reads like it changed something.

What it does instead: build the `opts` object the shipped JS actually reads out of a `Fingerprint`
row, concatenate the scripts in `SCRIPT_ORDER`, and install the result ONCE per context with
`BrowserContext.add_init_script(...)` — verified to cover every page in the context including pages
created later.

`playwright_stealth` ships no `py.typed`, so mypy resolves `SCRIPTS` to `Any` and CANNOT catch a
typo in a script name; `tests/unit/test_stealth_script_names.py` is the only thing that does.

Callers must navigate to a real origin before asserting anything. On `about:blank`
`navigator.userAgent.js` throws (`deviceMemory` has no descriptor outside a secure context),
Playwright concatenates all init scripts into one, and the throw silently kills every LATER
script — including `webdriver`, which is the one that matters (03-RESEARCH.md Pitfall 3).

Named symbols: SCRIPT_ORDER, stealth_opts, build_init_script
"""
from __future__ import annotations

import json
from typing import Any

from playwright_stealth.core._stealth_config import SCRIPTS

from services.poller.sources.resy.fingerprints import Fingerprint

# The 16 shipped scripts, in the library's own order. `utils` MUST come first — every other script
# calls `utils.replaceGetterWithProxy` / `utils.makeHandler`. `navigator_hardware_concurrency` is
# absent on purpose: `navigator_user_agent` already sets `hardwareConcurrency` from the same
# `opts.navigator.hardwareConcurrency`, and running both would install a proxy over a proxy.
SCRIPT_ORDER: tuple[str, ...] = (
    "utils",
    "generate_magic_arrays",
    "chrome_app",
    "chrome_csi",
    "chrome_load_times",
    "chrome_runtime",
    "iframe_content_window",
    "media_codecs",
    "navigator_languages",
    "navigator_permissions",
    "navigator_plugins",
    "navigator_user_agent",
    "navigator_vendor",
    "webdriver",
    "outerdimensions",
    "webgl_vendor",
)


def stealth_opts(fp: Fingerprint) -> dict[str, Any]:
    """
    The `opts` object every shipped script reads, built entirely from `fp`.

    Nothing here may be invented independently of the row: `brands` must mirror `fp.sec_ch_ua`
    because a page reading `navigator.userAgentData.brands` and a server reading the `sec-ch-ua`
    header are asking the same question and must get the same answer.
    """
    return {
        "navigator": {
            "userAgent": fp.user_agent,
            "brands": [{"brand": b.brand, "version": b.version} for b in fp.brands],
            "doNotTrack": "1",
            "platform": fp.platform,
            "language": fp.languages[0],
            "languages": list(fp.languages),
            "appVersion": fp.user_agent.removeprefix("Mozilla/"),
            "vendor": "Google Inc.",
            "deviceMemory": fp.device_memory,
            "hardwareConcurrency": fp.hardware_concurrency,
            "maxTouchPoints": 0,
            "mobile": False,
            "productSub": "20030107",
        },
        "webgl": {"vendor": fp.webgl_vendor, "renderer": fp.webgl_renderer},
        "viewport": {
            "width": fp.viewport_width,
            "height": fp.viewport_height,
            "outerWidth": fp.viewport_width,
            "outerHeight": fp.viewport_height + 85,
            "innerWidth": fp.viewport_width,
            "innerHeight": fp.viewport_height,
        },
        "runOnInsecureOrigins": None,
    }


def build_init_script(fp: Fingerprint) -> str:
    """
    The single JS blob to hand to `BrowserContext.add_init_script` — once per context, never per page.

    `const opts = {...}` must come first: every script below it dereferences `opts` at top level, so
    a different order is a `ReferenceError` in script one and silence in all fifteen after it.
    """
    prefix = f"const opts = {json.dumps(stealth_opts(fp))}"
    scripts: list[str] = [str(SCRIPTS[name]) for name in SCRIPT_ORDER]
    return "\n".join([prefix, *scripts])
