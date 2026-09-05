"""Unit tests for the Phase 2 additions to shared.redis_keys (D-42).

Every Redis key pattern and TTL Phase 2 introduces is declared exactly once in
``shared/redis_keys.py``; these tests pin the strings and the constants so a
rename is a deliberate, visible change rather than a silent keyspace orphan.
"""
from shared.redis_keys import (
    AVAIL_STATE_TTL_SECONDS,
    CONFIRM_DELAY_MS,
    EVENT_IDEMPOTENCY_TTL_SECONDS,
    EXPEDITE_FLAG_TTL_SECONDS,
    EXPEDITE_POLL_LUA,
    avail_meta_key,
    avail_state_key,
    event_idempotency_key,
    sched_expedite_key,
)


def _lua_body(script: str) -> str:
    """Strip full-line ``--`` comments so an explanatory comment can never satisfy
    or break a content gate (the script documents why 'GT' is wrong, in a comment)."""
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("--")
    )


def test_sched_expedite_key_format():
    assert sched_expedite_key("opentable:42") == "sched:expedite:opentable:42"
    assert sched_expedite_key("resy:7") == "sched:expedite:resy:7"


def test_expedite_constants():
    assert CONFIRM_DELAY_MS == 8_000
    assert EXPEDITE_FLAG_TTL_SECONDS == 120


def test_expedite_lua_uses_xx_and_lt_flags():
    """XX must not resurrect an in-flight job; LT must not raise an earlier score."""
    body = _lua_body(EXPEDITE_POLL_LUA)
    assert "'XX'" in body
    assert "'LT'" in body
    assert "ZSCORE" in body
    assert "ZADD" in body
    # Plain ZADD without XX would create the member; GT would push the poll later.
    assert "'GT'" not in body


def test_expedite_lua_sets_the_flag_atomically_with_its_ttl():
    """The in-flight branch is a single SET ... EX — never SET followed by EXPIRE."""
    body = _lua_body(EXPEDITE_POLL_LUA)
    assert "'SET'" in body
    assert "'EX'" in body
    assert "EXPIRE" not in body
    # GETDEL is the consumer's job (LuaScheduler.consume_expedite), not the script's.
    assert "GETDEL" not in body


def test_expedite_lua_returns_the_two_documented_branch_names():
    body = _lua_body(EXPEDITE_POLL_LUA)
    assert "'zset'" in body
    assert "'flag'" in body


def test_expedite_lua_declares_its_keys_and_argv_header():
    """Mirrors the CLAIM_POLL_LUA header form so the calling convention is readable."""
    for marker in ("KEYS[1]", "KEYS[2]", "ARGV[1]", "ARGV[2]", "ARGV[3]", "ARGV[4]"):
        assert marker in EXPEDITE_POLL_LUA


# -- Availability state keys (D-40, D-42, STATE-01) --


def test_avail_state_key_format():
    assert avail_state_key(42, "2026-05-01", 2) == "avail:42:2026-05-01:2"


def test_avail_meta_key_format():
    assert avail_meta_key(42) == "avail:42:meta"


def test_event_idempotency_key_format():
    """Components are percent-escaped (WR-04), so `:` inside a value cannot split the key."""
    assert (
        event_idempotency_key(42, "2026-05-01", 2, "19:00|bar", "tok1")
        == "event:42:2026-05-01:2:19%3A00%7Cbar:tok1"
    )


def test_availability_ttl_constants():
    assert AVAIL_STATE_TTL_SECONDS == 90_000      # 25 h
    assert EVENT_IDEMPOTENCY_TTL_SECONDS == 1_200  # 20 min


def test_adjacent_party_sizes_never_collide():
    """Adjacency edge (STATE-01): neighbouring party sizes are distinct keys."""
    assert avail_state_key(42, "2026-05-01", 2) != avail_state_key(42, "2026-05-01", 4)
    assert avail_state_key(42, "2026-05-01", 2) != avail_state_key(42, "2026-05-02", 2)
    assert avail_state_key(42, "2026-05-01", 2) != avail_state_key(43, "2026-05-01", 2)


def test_idempotency_keys_differing_only_in_token_are_distinct():
    a = event_idempotency_key(42, "2026-05-01", 2, "19:00|bar", "tok1")
    b = event_idempotency_key(42, "2026-05-01", 2, "19:00|bar", "tok2")
    assert a != b


def test_idempotency_keys_differing_only_in_seat_type_are_distinct():
    """CR-01 regression: seat_type is slot identity (D-36) and OpenTable shares one token
    across every seating type of a timeslot, so the claim key MUST separate them."""
    bar = event_idempotency_key(42, "2026-05-01", 2, "19:00|bar", "shared-token")
    standard = event_idempotency_key(42, "2026-05-01", 2, "19:00|standard", "shared-token")
    assert bar != standard


def test_idempotency_keys_differing_only_in_time_slot_are_distinct():
    a = event_idempotency_key(42, "2026-05-01", 2, "19:00|bar", "shared-token")
    b = event_idempotency_key(42, "2026-05-01", 2, "20:00|bar", "shared-token")
    assert a != b


def test_the_claim_key_is_injective_over_components_that_contain_the_separator():
    """WR-04: an unescaped join collapsed two distinct slot identities onto one key.

    `slot_key` is `f"{time_slot}|{seat_type or '-'}"` and both halves — like `token` — come
    straight from the payload, which `parsers/opentable.py` only isinstance-checks. A time
    slot ALWAYS contains a `:`, so this is the ordinary case, not an exotic one:
    `("19:00|bar", "a:b")` and `("19:00|bar:a", "b")` used to render the same key, and the
    second confirmed opening would have been claimed away by the first.
    """
    components = ["", "-", "a", "a:b", ":", "19:00|bar", "19:00|bar:a", "b", "%3A", "%"]
    seen: dict[str, tuple] = {}
    for slot_key in components:
        for token in components:
            for date in ("", "2026-05-01", "2026:05:01"):
                identity = (slot_key, token, date)
                key = event_idempotency_key(42, date, 2, slot_key, token)
                clash = seen.setdefault(key, identity)
                assert clash == identity, (
                    f"{identity} and {clash} both render {key!r}: one confirmed opening "
                    "would silently claim the other's key and be dropped"
                )


def test_the_claim_key_is_injective_across_the_numeric_components():
    """A restaurant id or party size cannot be made to eat the next field either."""
    assert event_idempotency_key(4, "2:2026-05-01", 2, "s", "t") != event_idempotency_key(
        42, "2026-05-01", 2, "s", "t"
    )


def test_key_builders_are_total_and_touch_no_redis():
    """Empty edge (STATE-01): pure string builders, no IO, no failure mode."""
    assert avail_state_key(0, "", 0) == "avail:0::0"
    assert avail_meta_key(0) == "avail:0:meta"
    assert event_idempotency_key(0, "", 0, "", "") == "event:0::0::"


def test_the_surviving_hash_helpers_are_exported_so_store_needs_no_casts():
    """D-42 / Pitfall 3: every cast(Awaitable[T], ...) lives in one module.

    That invariant is satisfied by the `_with_ttl` transactions the store actually calls; it
    was NOT a reason to keep the bare mutations alive. The old form of this test asserted all
    five originals remained callable, which told the next cleanup pass that four callerless
    functions were load-bearing (IN-06).
    """
    import shared.redis_keys as rk

    for name in (
        "hgetall_slots",
        "hset_slot_with_ttl",
        "hdel_slot_with_ttl",
        "hset_meta_with_ttl",
    ):
        assert callable(getattr(rk, name)), f"{name} missing from shared.redis_keys"


def test_the_non_atomic_hash_helpers_stay_deleted():
    """WR-03: a bare mutation plus a separate EXPIRE is the shape WR-10 removed.

    Re-adding one is two lines and lints clean, and `test_no_setnx_expire_pairs.py` only
    greps for `.setnx(`, so nothing else stands in the way.
    """
    import shared.redis_keys as rk

    for gone in ("hset_slot", "hdel_slot", "hset_meta", "expire_key"):
        assert not hasattr(rk, gone), (
            f"{gone} is the non-atomic mutate-then-EXPIRE shape WR-10 removed; use the "
            "matching _with_ttl transaction instead"
        )
