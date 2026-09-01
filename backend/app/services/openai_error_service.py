from dataclasses import dataclass


@dataclass(frozen=True)
class OpenAIErrorDetails:
    http_status: int
    reason_code: str
    message: str


def describe_openai_error(
    error: Exception,
    *,
    default_reason_code: str,
    default_message: str,
) -> OpenAIErrorDetails:
    provider_status = getattr(error, "status_code", None)
    provider_code = getattr(error, "code", None)

    if provider_code in {"credit_balance_exhausted", "insufficient_quota"}:
        return OpenAIErrorDetails(
            http_status=503,
            reason_code="OPENAI_CREDITS_EXHAUSTED",
            message=(
                "The configured OpenAI API project has no credits remaining. "
                "Add API credits and retry the request."
            ),
        )

    if provider_status == 401:
        return OpenAIErrorDetails(
            http_status=503,
            reason_code="OPENAI_AUTHENTICATION_FAILED",
            message="The configured OpenAI API key was rejected.",
        )

    if provider_status == 429:
        return OpenAIErrorDetails(
            http_status=503,
            reason_code="OPENAI_RATE_LIMITED",
            message="The OpenAI API rate limit was reached. Retry later.",
        )

    if provider_status == 400 and provider_code == "invalid_value":
        return OpenAIErrorDetails(
            http_status=422,
            reason_code="OPENAI_INPUT_REJECTED",
            message="The OpenAI API rejected the supplied input.",
        )

    return OpenAIErrorDetails(
        http_status=502,
        reason_code=default_reason_code,
        message=default_message,
    )
