"""Unit tests for the Phase 2 additions to shared.redis_keys (D-42).

Every Redis key pattern and TTL Phase 2 introduces is declared exactly once in
``shared/redis_keys.py``; these tests pin the strings and the constants so a
rename is a deliberate, visible change rather than a silent keyspace orphan.
"""
from shared.redis_keys import (
    CONFIRM_DELAY_MS,
    EXPEDITE_FLAG_TTL_SECONDS,
    EXPEDITE_POLL_LUA,
    sched_expedite_key,
)


def test_sched_expedite_key_format():
    assert sched_expedite_key("opentable:42") == "sched:expedite:opentable:42"
    assert sched_expedite_key("resy:7") == "sched:expedite:resy:7"


def test_expedite_constants():
    assert CONFIRM_DELAY_MS == 8_000
    assert EXPEDITE_FLAG_TTL_SECONDS == 120


def test_expedite_lua_uses_xx_and_lt_flags():
    """XX must not resurrect an in-flight job; LT must not raise an earlier score."""
    assert "'XX'" in EXPEDITE_POLL_LUA
    assert "'LT'" in EXPEDITE_POLL_LUA
    assert "ZSCORE" in EXPEDITE_POLL_LUA
    assert "ZADD" in EXPEDITE_POLL_LUA
    # Plain ZADD without XX would create the member; GT would push the poll later.
    assert "'GT'" not in EXPEDITE_POLL_LUA


def test_expedite_lua_sets_the_flag_atomically_with_its_ttl():
    """The in-flight branch is a single SET ... EX — never SET followed by EXPIRE."""
    assert "'SET'" in EXPEDITE_POLL_LUA
    assert "'EX'" in EXPEDITE_POLL_LUA
    assert "EXPIRE" not in EXPEDITE_POLL_LUA
    # GETDEL is the consumer's job (LuaScheduler.consume_expedite), not the script's.
    assert "GETDEL" not in EXPEDITE_POLL_LUA


def test_expedite_lua_returns_the_two_documented_branch_names():
    assert "'zset'" in EXPEDITE_POLL_LUA
    assert "'flag'" in EXPEDITE_POLL_LUA


def test_expedite_lua_declares_its_keys_and_argv_header():
    """Mirrors the CLAIM_POLL_LUA header form so the calling convention is readable."""
    for marker in ("KEYS[1]", "KEYS[2]", "ARGV[1]", "ARGV[2]", "ARGV[3]", "ARGV[4]"):
        assert marker in EXPEDITE_POLL_LUA
