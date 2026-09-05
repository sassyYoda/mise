"""Unit tests for shared.telemetry secret-redaction processor."""
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
