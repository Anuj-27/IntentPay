from backend.app.services.openai_error_service import describe_openai_error


class ProviderError(Exception):
    def __init__(self, status_code, code):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def describe(error):
    return describe_openai_error(
        error,
        default_reason_code="PROVIDER_ERROR",
        default_message="Provider request failed.",
    )


def test_exhausted_credits_are_reported_clearly():
    result = describe(ProviderError(429, "credit_balance_exhausted"))

    assert result.http_status == 503
    assert result.reason_code == "OPENAI_CREDITS_EXHAUSTED"
    assert "credits" in result.message.casefold()


def test_authentication_and_rate_limits_are_distinct():
    authentication = describe(ProviderError(401, "invalid_api_key"))
    rate_limit = describe(ProviderError(429, "rate_limit_exceeded"))

    assert authentication.reason_code == "OPENAI_AUTHENTICATION_FAILED"
    assert rate_limit.reason_code == "OPENAI_RATE_LIMITED"


def test_unknown_provider_error_uses_safe_default():
    result = describe(ProviderError(500, "provider_failure"))

    assert result.http_status == 502
    assert result.reason_code == "PROVIDER_ERROR"
    assert result.message == "Provider request failed."
