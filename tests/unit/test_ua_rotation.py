"""Unit tests for User-Agent rotation (T-03)."""
from __future__ import annotations

from services.poller.config import USER_AGENTS, random_user_agent


def test_user_agents_list_has_min_four_entries():
    assert len(USER_AGENTS) >= 4, (
        f"T-03 requires >=4 UAs, got {len(USER_AGENTS)}"
    )


def test_user_agents_are_unique():
    assert len(set(USER_AGENTS)) == len(USER_AGENTS), (
        "USER_AGENTS contains duplicates"
    )


def test_user_agents_are_real_browser_strings():
    for ua in USER_AGENTS:
        assert "Mozilla/5.0" in ua, f"UA missing real browser prefix: {ua!r}"


def test_random_user_agent_returns_from_list():
    for _ in range(20):
        assert random_user_agent() in USER_AGENTS


def test_random_user_agent_rotates_across_calls():
    seen = {random_user_agent() for _ in range(200)}
    assert len(seen) >= 2, "random_user_agent must rotate across calls (T-03)"
