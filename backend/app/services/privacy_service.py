from collections.abc import Mapping, Sequence
from typing import Any


REDACTED_VALUE = "[REDACTED]"

SENSITIVE_FIELD_NAMES = {
    "api_key",
    "authorization",
    "cookie",
    "idempotency_key",
    "openai_api_key",
    "password",
    "payment_signature",
    "proxy_authorization",
    "razorpay_key_secret",
    "razorpay_signature",
    "refresh_token",
    "secret",
    "set_cookie",
    "token",
    "webhook_secret",
}


def normalize_field_name(value: Any) -> str:
    return str(value).strip().casefold().replace("-", "_")


def redact_sensitive_data(value: Any) -> Any:
    """Return an audit-safe copy without changing the caller's object."""

    if isinstance(value, Mapping):
        redacted = {}

        for key, nested_value in value.items():
            if normalize_field_name(key) in SENSITIVE_FIELD_NAMES:
                redacted[key] = REDACTED_VALUE
            else:
                redacted[key] = redact_sensitive_data(nested_value)

        return redacted

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [redact_sensitive_data(item) for item in value]

    return value

