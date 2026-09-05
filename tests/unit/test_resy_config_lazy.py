"""Unit: every Resy setting is read at CALL time, and the defaults are pinned (D-63, D-72).

`services/poller/config.py` froze `KAFKA_BOOTSTRAP_SERVERS`, `REDIS_URL` and
`DATABASE_URL_ASYNC` into module constants at import time. The consequence was not
theoretical: an integration module that imported poller code during collection pinned a
whole run to the localhost defaults instead of its testcontainers, and
`tests/integration/test_poller_expedite_release.py` still carries an explicit
`sys.modules` eviction to work around it (the 02-02 deviation).

Repeating that mistake for `RESY_ENABLED` would be worse than inconvenient. Whichever
module imported first would decide, for the life of the process, whether the fleet
launches Chromium — and the wrong answer in either direction is invisible: `false` when it
should be `true` means a silently idle fleet, `true` when it should be `false` means real
requests to resy.com from a test run.

So this file asserts two things the rest of the suite cannot: that every new setting reads
its environment when it is CALLED, and that no new module-level `os.getenv` assignment has
been added to the file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.poller import config

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "services" / "poller" / "config.py"

# Every Resy setting this plan adds, as (function name, env var).
RESY_SETTINGS: tuple[tuple[str, str], ...] = (
    ("resy_enabled", "RESY_ENABLED"),
    ("resy_api_base", "RESY_API_BASE"),
    ("resy_api_key", "RESY_API_KEY"),
    ("resy_auth_token_header", "RESY_AUTH_TOKEN_HEADER"),
    ("resy_accounts_json", "RESY_ACCOUNTS_JSON"),
    ("resy_proxy_url", "RESY_PROXY_URL"),
    ("resy_contexts", "RESY_CONTEXTS"),
    ("resy_global_rpm", "RESY_GLOBAL_RPM"),
    ("resy_baseline_interval_seconds", "RESY_BASELINE_INTERVAL_SECONDS"),
    ("resy_date_range_days", "RESY_DATE_RANGE_DAYS"),
    ("resy_party_sizes", "RESY_PARTY_SIZES"),
    ("metrics_port", "METRICS_PORT"),
    ("poll_workers", "POLL_WORKERS"),
)

# The integer readers and the value each returns with nothing set.
INTEGER_DEFAULTS: tuple[tuple[str, str, int], ...] = (
    ("resy_contexts", "RESY_CONTEXTS", 4),
    ("resy_global_rpm", "RESY_GLOBAL_RPM", 80),
    ("resy_baseline_interval_seconds", "RESY_BASELINE_INTERVAL_SECONDS", 180),
    ("resy_date_range_days", "RESY_DATE_RANGE_DAYS", 3),
    ("metrics_port", "METRICS_PORT", 9101),
)

ALL_RESY_ENV_VARS: tuple[str, ...] = tuple(env for _, env in RESY_SETTINGS)


@pytest.fixture(autouse=True)
def clean_resy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from a genuinely unset environment.

    A developer with RESY_ENABLED=true in their shell must not see a different suite from
    CI, and a test that sets a variable must not leak it into the next one.
    """
    for name in ALL_RESY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------------------
# Every setting is a zero-argument function, and it reads the environment when called
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name,_env", RESY_SETTINGS)
def test_every_setting_is_a_zero_argument_function(name: str, _env: str) -> None:
    import inspect

    fn = getattr(config, name, None)
    assert fn is not None, f"{name} is missing from services/poller/config.py"
    assert callable(fn), f"{name} must be a function, not a module constant"
    required = [
        p
        for p in inspect.signature(fn).parameters.values()
        if p.default is inspect.Parameter.empty
    ]
    assert required == [], f"{name} must take no required arguments, got {required}"


def test_resy_enabled_reads_the_environment_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property a module constant cannot have: the SAME interpreter, a NEW answer."""
    assert config.resy_enabled() is False
    monkeypatch.setenv("RESY_ENABLED", "true")
    assert config.resy_enabled() is True
    monkeypatch.setenv("RESY_ENABLED", "false")
    assert config.resy_enabled() is False


def test_resy_api_base_reads_the_environment_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is how an integration test points the adapter at the local stub."""
    assert config.resy_api_base() == "https://api.resy.com"
    monkeypatch.setenv("RESY_API_BASE", "http://127.0.0.1:54321")
    assert config.resy_api_base() == "http://127.0.0.1:54321"


def test_resy_contexts_reads_the_environment_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert config.resy_contexts() == 4
    monkeypatch.setenv("RESY_CONTEXTS", "2")
    assert config.resy_contexts() == 2


def test_resy_api_key_reads_the_environment_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert config.resy_api_key() is None
    monkeypatch.setenv("RESY_API_KEY", "k-123")
    assert config.resy_api_key() == "k-123"


# --------------------------------------------------------------------------------------
# RESY_ENABLED truthiness
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "false", "FALSE", "0", "no", "off", "  false  "])
def test_resy_enabled_is_false_for(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESY_ENABLED", raw)
    assert config.resy_enabled() is False


@pytest.mark.parametrize("raw", ["true", "TRUE", "True", "1", "yes", "  true  "])
def test_resy_enabled_is_true_for(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESY_ENABLED", raw)
    assert config.resy_enabled() is True


def test_resy_enabled_is_false_when_unset() -> None:
    """The default is the whole safety property: an unconfigured deployment polls nothing."""
    assert config.resy_enabled() is False


# --------------------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name,_env,expected", INTEGER_DEFAULTS)
def test_integer_default(name: str, _env: str, expected: int) -> None:
    assert getattr(config, name)() == expected


def test_resy_party_sizes_defaults_to_two() -> None:
    assert config.resy_party_sizes() == [2]


def test_resy_party_sizes_parses_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESY_PARTY_SIZES", "2, 4 ,6")
    assert config.resy_party_sizes() == [2, 4, 6]


def test_resy_party_sizes_refuses_a_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESY_PARTY_SIZES", "2,two")
    with pytest.raises(RuntimeError, match="RESY_PARTY_SIZES"):
        config.resy_party_sizes()


def test_string_defaults() -> None:
    assert config.resy_api_base() == "https://api.resy.com"
    # A5: a sibling header `X-Resy-Universal-Auth` also exists and may turn out to be the
    # right one. The NAME lives in config precisely so correcting it is not an adapter edit.
    assert config.resy_auth_token_header() == "X-Resy-Auth-Token"
    assert config.resy_api_key() is None
    assert config.resy_proxy_url() is None
    assert config.resy_accounts_json() == ""


def test_a_trailing_slash_on_the_api_base_is_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter builds `f"{base}/4/find"`; a doubled slash is a 404 nobody expects."""
    monkeypatch.setenv("RESY_API_BASE", "https://api.resy.com/")
    assert config.resy_api_base() == "https://api.resy.com"


def test_an_empty_api_key_is_none_not_an_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`RESY_API_KEY=` in a .env file means "not captured yet", not "the key is ''"."""
    monkeypatch.setenv("RESY_API_KEY", "   ")
    assert config.resy_api_key() is None


# --------------------------------------------------------------------------------------
# Integer parsing refuses a typo instead of swallowing it into the default
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name,env,_default", INTEGER_DEFAULTS)
def test_a_non_integer_raises_and_names_the_variable(
    name: str, env: str, _default: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silently-defaulted RESY_GLOBAL_RPM would poll at 80 rpm when the operator meant 8.

    The public README promises <= 80 req/min. An operator who lowers it and gets 80
    anyway, with no error, has been given the opposite of what they asked for.
    """
    monkeypatch.setenv(env, "eighty")
    with pytest.raises(RuntimeError, match=env):
        getattr(config, name)()


@pytest.mark.parametrize("name,env,default", INTEGER_DEFAULTS)
def test_an_empty_integer_variable_falls_back_to_the_default(
    name: str, env: str, default: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`RESY_CONTEXTS=` in an .env file is "unset", not a typo."""
    monkeypatch.setenv(env, "")
    assert getattr(config, name)() == default


# --------------------------------------------------------------------------------------
# poll_workers (D-72)
# --------------------------------------------------------------------------------------


def test_poll_workers_is_one_when_resy_is_disabled() -> None:
    """Today's exact behaviour: main.py runs a single poll_loop."""
    assert config.poll_workers() == 1


def test_poll_workers_is_one_per_context_plus_one_when_resy_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-72: one worker per Resy context, plus one so OpenTable is never fully starved."""
    monkeypatch.setenv("RESY_ENABLED", "true")
    assert config.poll_workers() == 5
    monkeypatch.setenv("RESY_CONTEXTS", "2")
    assert config.poll_workers() == 3


@pytest.mark.parametrize("resy", ["true", "false"])
def test_an_explicit_poll_workers_override_wins(
    resy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESY_ENABLED", resy)
    monkeypatch.setenv("POLL_WORKERS", "7")
    assert config.poll_workers() == 7


def test_poll_workers_refuses_a_non_integer_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLL_WORKERS", "many")
    with pytest.raises(RuntimeError, match="POLL_WORKERS"):
        config.poll_workers()


def test_poll_workers_refuses_a_zero_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero workers is a poller that starts, logs nothing wrong, and polls nothing."""
    monkeypatch.setenv("POLL_WORKERS", "0")
    with pytest.raises(RuntimeError, match="POLL_WORKERS"):
        config.poll_workers()


# --------------------------------------------------------------------------------------
# Source scan: no NEW module-level os.getenv assignment
# --------------------------------------------------------------------------------------

_FULL_LINE_COMMENT = re.compile(r"^\s*#")
# A module-level assignment is one that starts in column 0.
_MODULE_LEVEL_GETENV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*os\.getenv")

# The three that predate this plan. They are LEFT ALONE deliberately — other modules import
# them and 03-03 owns none of those call sites — but nothing may join them.
LEGACY_MODULE_CONSTANTS = {
    "KAFKA_BOOTSTRAP_SERVERS",
    "REDIS_URL",
    "DATABASE_URL_ASYNC",
}


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Strip full-line comments so the explanatory docstring cannot break the gate."""
    return [
        (lineno, line)
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if not _FULL_LINE_COMMENT.match(line)
    ]


def test_the_scanned_file_is_not_empty() -> None:
    """A path typo would make the scan below vacuously pass forever."""
    assert CONFIG_PATH.is_file(), CONFIG_PATH
    text = CONFIG_PATH.read_text()
    assert len(text) > 1_000, f"config.py is suspiciously short: {len(text)} chars"
    assert "def resy_enabled" in text, "the scan is pointed at the wrong file"


def test_no_new_module_level_getenv_was_added() -> None:
    found = {
        match.group(1)
        for _lineno, line in _code_lines(CONFIG_PATH)
        if (match := _MODULE_LEVEL_GETENV.match(line))
    }
    assert found == LEGACY_MODULE_CONSTANTS, (
        "a new module-level os.getenv freezes the environment at import time, which is "
        f"the 02-02 defect this plan exists to avoid repeating. Unexpected: "
        f"{sorted(found - LEGACY_MODULE_CONSTANTS)}; missing: "
        f"{sorted(LEGACY_MODULE_CONSTANTS - found)}"
    )


def test_the_source_scan_would_catch_a_new_constant() -> None:
    """Non-vacuity: prove the regex matches the shape it claims to forbid."""
    assert _MODULE_LEVEL_GETENV.match('RESY_ENABLED: str = os.getenv("RESY_ENABLED", "")')
    assert _MODULE_LEVEL_GETENV.match("RESY_CONTEXTS = os.getenv('RESY_CONTEXTS')")
    assert not _MODULE_LEVEL_GETENV.match('    raw = os.getenv("RESY_ENABLED")')


def test_every_new_setting_is_exported() -> None:
    """`__all__` is what lets another module import these under mypy --strict."""
    exported = set(config.__all__)
    for name, _env in RESY_SETTINGS:
        assert name in exported, f"{name} missing from services.poller.config.__all__"
