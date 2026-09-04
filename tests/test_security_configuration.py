import pytest
from fastapi import Response

from backend.app.services.merchant_auth_service import set_session_cookie
from backend.app.services.security_service import (
    DEFAULT_SESSION_SECRET,
    validate_security_configuration,
)


def test_local_mode_keeps_the_easy_demo_default(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("MERCHANT_SESSION_SECRET", raising=False)

    # The local learner/demo path remains usable without additional setup.
    validate_security_configuration()


def test_production_rejects_missing_or_default_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MERCHANT_SESSION_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="MERCHANT_SESSION_SECRET"):
        validate_security_configuration()

    monkeypatch.setenv("MERCHANT_SESSION_SECRET", DEFAULT_SESSION_SECRET)
    with pytest.raises(RuntimeError, match="MERCHANT_SESSION_SECRET"):
        validate_security_configuration()


def test_production_requires_a_long_unique_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MERCHANT_SESSION_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="32 characters"):
        validate_security_configuration()


def test_production_session_cookie_is_secure(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MERCHANT_SESSION_SECRET", "x" * 48)
    response = Response()

    set_session_cookie(response, "merchant-1")

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
