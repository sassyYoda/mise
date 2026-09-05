"""Unit tests for shared.telemetry secret-redaction processor."""
import pytest

from shared.telemetry import _redact_secrets


def test_redacts_twilio_auth_token():
    event = {"event": "test", "TWILIO_AUTH_TOKEN": "secret123"}
    result = _redact_secrets(None, "info", event)
    assert result["TWILIO_AUTH_TOKEN"] == "[REDACTED]"


def test_redacts_hmac_secret():
    event = {"event": "test", "HMAC_MGMT_SECRET_V1": "deadbeef" * 4}
    result = _redact_secrets(None, "info", event)
    assert result["HMAC_MGMT_SECRET_V1"] == "[REDACTED]"


def test_redacts_vapid_private_key():
    event = {"event": "test", "VAPID_PRIVATE_KEY": "very_private"}
    result = _redact_secrets(None, "info", event)
    assert result["VAPID_PRIVATE_KEY"] == "[REDACTED]"


def test_redacts_resy_accounts_json():
    event = {"RESY_ACCOUNTS_JSON": '[{"email":"x","cookies":{}}]', "event": "poll"}
    result = _redact_secrets(None, "info", event)
    assert result["RESY_ACCOUNTS_JSON"] == "[REDACTED]"


def test_leaves_non_secret_fields_alone():
    event = {"event": "poll_completed", "restaurant_id": 42, "status": "success"}
    result = _redact_secrets(None, "info", event)
    assert result["restaurant_id"] == 42
    assert result["status"] == "success"


# --- Phase 3 (D-61a, research B-6): the eight secret-bearing keys the Resy fleet introduces ---
#
# Before this block, six of the eight leaked in full — including the proxy URL with its
# embedded credentials. Each key below is one reproduced leak, and each assertion is the
# regression guard for it. A cookie or an `X-Resy-Auth-Token` is a THIRD PARTY's credential
# replayed under a human's supervision; it never belongs in a log line, a stack trace, or
# (from Phase 7) a Sentry event.


@pytest.mark.parametrize(
    "key",
    [
        "cookie",
        "Cookie",
        "COOKIE",
        "cookies",
        "set-cookie",
        "Set-Cookie",
        "auth_token",
        "AUTH_TOKEN",
        "x-resy-auth-token",
        "X-Resy-Auth-Token",
        "authorization",
        "Authorization",
        "api_key",
        "API_KEY",
        "RESY_API_KEY",
        "resy_api_key",
    ],
)
def test_redacts_every_secret_bearing_key_case_insensitively(key):
    """Header names arrive in whatever casing the caller used; matching must not care."""
    event = {"event": "resy_poll", key: "SECRET-VALUE-abc123"}
    result = _redact_secrets(None, "info", event)
    assert result[key] == "[REDACTED]", f"{key!r} leaked its value"


def test_proxy_url_keeps_its_host_but_masks_the_credentials():
    """An operator must still see WHICH proxy was in play; the password must not survive."""
    event = {"RESY_PROXY_URL": "http://user:pass@proxy.example.com:8080"}
    result = _redact_secrets(None, "info", event)
    value = result["RESY_PROXY_URL"]
    assert "pass" not in value
    assert "user" not in value
    assert "proxy.example.com:8080" in value
    assert value.startswith("http://")


@pytest.mark.parametrize("key", ["proxy_url", "PROXY_URL", "resy_proxy_url"])
def test_proxy_url_masking_is_case_insensitive(key):
    event = {key: "socks5://bob:hunter2@residential.example.net:1080"}
    result = _redact_secrets(None, "info", event)
    assert "hunter2" not in result[key]
    assert "residential.example.net:1080" in result[key]


def test_a_proxy_url_without_credentials_is_left_readable():
    """Nothing to mask means nothing is hidden — the diagnostic value is the point."""
    event = {"RESY_PROXY_URL": "http://proxy.example.com:8080"}
    result = _redact_secrets(None, "info", event)
    assert result["RESY_PROXY_URL"] == "http://proxy.example.com:8080"


def test_a_malformed_proxy_url_is_redacted_wholesale_rather_than_parsed():
    """If the value cannot be parsed as a URL, fail CLOSED — never emit it hoping it is safe."""
    event = {"RESY_PROXY_URL": "user:pass@not a url at all"}
    result = _redact_secrets(None, "info", event)
    assert "pass" not in result["RESY_PROXY_URL"]


def test_the_four_pre_existing_keys_still_redact():
    """The Phase 3 extension must not displace the Phase 1 set."""
    event = {
        "TWILIO_AUTH_TOKEN": "a",
        "HMAC_MGMT_SECRET_V1": "b",
        "VAPID_PRIVATE_KEY": "c",
        "RESY_ACCOUNTS_JSON": "d",
    }
    result = _redact_secrets(None, "info", event)
    assert set(result.values()) == {"[REDACTED]"}


def test_the_resy_account_password_prefix_rule_still_redacts():
    event = {"RESY_ACCOUNT_1_PASSWORD": "hunter2", "RESY_ACCOUNT_3_PASSWORD": "hunter3"}
    result = _redact_secrets(None, "info", event)
    assert result["RESY_ACCOUNT_1_PASSWORD"] == "[REDACTED]"
    assert result["RESY_ACCOUNT_3_PASSWORD"] == "[REDACTED]"


@pytest.mark.parametrize(
    "key, value",
    [
        ("restaurant_id", 42),
        ("latency_ms", 137),
        ("context_id", "ctx-0"),
        ("status", "banned"),
        ("token_source", "config.token"),
        ("cookie_count", 2),
    ],
)
def test_benign_keys_pass_through_untouched(key, value):
    """The redactor must not be over-broad: `cookie_count` is a count, not a cookie.

    An over-broad redactor is not merely noisy — it destroys the diagnostics that make an
    incident survivable, and it trains readers to ignore `[REDACTED]`.
    """
    result = _redact_secrets(None, "info", {"event": "poll", key: value})
    assert result[key] == value


def test_redaction_does_not_invent_keys():
    """Only the keys present in the event dict may appear in the output."""
    event = {"event": "poll", "cookie": "x"}
    result = _redact_secrets(None, "info", event)
    assert set(result) == {"event", "cookie"}
