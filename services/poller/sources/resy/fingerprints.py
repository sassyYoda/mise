"""
Browser fingerprint rotation table for the Resy context pool (POLL-04, D-60, D-60a, D-64a).

One `Fingerprint` row is everything a single `BrowserContext` needs so that what the JavaScript
runtime says about itself and what the HTTP wire says about it are the SAME claim.

Why every field lives on one row
--------------------------------
Research reproduced `tf-playwright-stealth` shipping a Linux Chrome 96 identity into a macOS
Chrome 140 context while the HTTP `User-Agent` header still said macOS (03-RESEARCH.md B-3). A
JS/HTTP disagreement, and a `navigator.platform` of `"Linux x86_x64"` that no real Chrome emits,
are each a HARDER bot signal than the `navigator.webdriver` flag anybody is trying to hide. So
the row carries the browser-side values (`platform`, `languages`, `hardware_concurrency`,
`device_memory`, WebGL vendor/renderer) and the wire-side values (`accept_language`, `sec_ch_ua`,
`sec_ch_ua_platform`) together, and `tests/unit/test_fingerprints.py` fails the build if any row's
two halves stop agreeing.

The wire half is not decoration: `context.request` is Node's HTTP client, not Chromium, and emits
no `Accept-Language`, no `sec-ch-ua*` and no `Sec-Fetch-*` of its own (03-RESEARCH.md B-9). Those
headers reach the server only because `ContextPool` passes them to `new_context(extra_http_headers=)`
from these fields. POLL-04's "realistic request headers" is satisfied here or nowhere.

CONTRACT enforced by tests/unit/test_fingerprints.py — read before editing a row:
  * >= 6 rows, every `user_agent` distinct.
  * Per row the OS token in the UA, `platform`, `sec_ch_ua_platform` and the WebGL vendor family
    all name the same operating system, and `sec_ch_ua` names the UA's major Chrome version.
  * `accept_language`'s first tag equals `languages[0]`.
  * No row's `user_agent` or `sec_ch_ua` contains a headless marker.
An assertion that fails is a broken ROW, not a wrong test: fix the data.

Named symbols: Brand, Fingerprint, FINGERPRINTS, fingerprint_for_index
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Brand:
    """One entry of `navigator.userAgentData.brands`; must mirror the row's `sec_ch_ua` string."""

    brand: str
    version: str


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """
    A coherent browser identity: the JS-visible half and the HTTP-visible half of one persona.

    `viewport` is a property rather than a field so the frozen row cannot hand out a shared
    mutable dict that a caller mutates into a fingerprint nobody chose.
    """

    user_agent: str
    viewport_width: int
    viewport_height: int
    locale: str
    timezone_id: str
    device_scale_factor: float
    platform: str
    languages: tuple[str, ...]
    accept_language: str
    sec_ch_ua: str
    sec_ch_ua_platform: str
    brands: tuple[Brand, ...]
    hardware_concurrency: int
    device_memory: int
    webgl_vendor: str
    webgl_renderer: str

    @property
    def viewport(self) -> dict[str, int]:
        """A fresh `{"width": ..., "height": ...}` for `Browser.new_context(viewport=...)`."""
        return {"width": self.viewport_width, "height": self.viewport_height}


def _chrome_brands(major: str, grease_brand: str, grease_version: str) -> tuple[Brand, ...]:
    """The three-entry brand list real Chrome reports, in the row's own GREASE flavour."""
    return (
        Brand("Chromium", major),
        Brand(grease_brand, grease_version),
        Brand("Google Chrome", major),
    )


_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
)
_WIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
)

# Every row is New-York-local on purpose: the fleet polls NYC venues, and a Chicago timezone on a
# session booking a Manhattan table is a coherence defect of exactly the kind this table exists to
# prevent. `device_memory` never exceeds 8 because Chrome clamps `navigator.deviceMemory` at 8.
FINGERPRINTS: tuple[Fingerprint, ...] = (
    Fingerprint(
        user_agent=_MAC_UA.format(major=140),
        viewport_width=1512,
        viewport_height=945,
        locale="en-US",
        timezone_id="America/New_York",
        device_scale_factor=2.0,
        platform="MacIntel",
        languages=("en-US", "en"),
        accept_language="en-US,en;q=0.9",
        sec_ch_ua='"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        sec_ch_ua_platform='"macOS"',
        brands=_chrome_brands("140", "Not=A?Brand", "24"),
        hardware_concurrency=10,
        device_memory=8,
        webgl_vendor="Google Inc. (Apple)",
        webgl_renderer="ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro, Unspecified Version)",
    ),
    Fingerprint(
        user_agent=_WIN_UA.format(major=140),
        viewport_width=1920,
        viewport_height=1080,
        locale="en-US",
        timezone_id="America/New_York",
        device_scale_factor=1.0,
        platform="Win32",
        languages=("en-US", "en"),
        accept_language="en-US,en;q=0.9",
        sec_ch_ua='"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        sec_ch_ua_platform='"Windows"',
        brands=_chrome_brands("140", "Not=A?Brand", "24"),
        hardware_concurrency=16,
        device_memory=8,
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer=(
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"
        ),
    ),
    Fingerprint(
        user_agent=_MAC_UA.format(major=139),
        viewport_width=1440,
        viewport_height=900,
        locale="en-US",
        timezone_id="America/New_York",
        device_scale_factor=2.0,
        platform="MacIntel",
        languages=("en-US", "en"),
        accept_language="en-US,en;q=0.9",
        sec_ch_ua='"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
        sec_ch_ua_platform='"macOS"',
        brands=(
            Brand("Not;A=Brand", "99"),
            Brand("Google Chrome", "139"),
            Brand("Chromium", "139"),
        ),
        hardware_concurrency=8,
        device_memory=8,
        webgl_vendor="Google Inc. (Apple)",
        webgl_renderer="ANGLE (Apple, ANGLE Metal Renderer: Apple M1 Pro, Unspecified Version)",
    ),
    Fingerprint(
        user_agent=_WIN_UA.format(major=139),
        viewport_width=1536,
        viewport_height=864,
        locale="en-US",
        timezone_id="America/New_York",
        device_scale_factor=1.25,
        platform="Win32",
        languages=("en-US", "en"),
        accept_language="en-US,en;q=0.9",
        sec_ch_ua='"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
        sec_ch_ua_platform='"Windows"',
        brands=(
            Brand("Not;A=Brand", "99"),
            Brand("Google Chrome", "139"),
            Brand("Chromium", "139"),
        ),
        hardware_concurrency=12,
        device_memory=8,
        webgl_vendor="Google Inc. (Intel)",
        webgl_renderer=(
            "ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) Direct3D11 vs_5_0 ps_5_0, D3D11)"
        ),
    ),
    Fingerprint(
        user_agent=_MAC_UA.format(major=141),
        viewport_width=1680,
        viewport_height=1050,
        locale="en-US",
        timezone_id="America/New_York",
        device_scale_factor=2.0,
        platform="MacIntel",
        languages=("en-US", "en"),
        accept_language="en-US,en;q=0.9",
        sec_ch_ua='"Chromium";v="141", "Not?A_Brand";v="8", "Google Chrome";v="141"',
        sec_ch_ua_platform='"macOS"',
        brands=_chrome_brands("141", "Not?A_Brand", "8"),
        hardware_concurrency=8,
        device_memory=8,
        webgl_vendor="Google Inc. (Apple)",
        webgl_renderer="ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",
    ),
    Fingerprint(
        user_agent=_WIN_UA.format(major=141),
        viewport_width=1366,
        viewport_height=768,
        locale="en-US",
        timezone_id="America/New_York",
        device_scale_factor=1.0,
        platform="Win32",
        languages=("en-US", "en"),
        accept_language="en-US,en;q=0.9",
        sec_ch_ua='"Chromium";v="141", "Not?A_Brand";v="8", "Google Chrome";v="141"',
        sec_ch_ua_platform='"Windows"',
        brands=_chrome_brands("141", "Not?A_Brand", "8"),
        hardware_concurrency=8,
        device_memory=8,
        webgl_vendor="Google Inc. (AMD)",
        webgl_renderer="ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    ),
)


def fingerprint_for_index(i: int) -> Fingerprint:
    """
    Round-robin selection, NOT `random.choice`.

    Rotation is per CONTEXT, and a context outlives many requests on one cookie jar. Drawing a new
    identity at random per request would mean one authenticated session whose User-Agent changes
    mid-conversation — which is itself a stronger signal than any single fingerprint. Round-robin
    also makes "context 3 has been using row 3 all along" reproducible in a bug report.
    """
    return FINGERPRINTS[i % len(FINGERPRINTS)]
