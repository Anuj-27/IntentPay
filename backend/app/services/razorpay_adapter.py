import hashlib
import hmac
import os
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from backend.app.schemas.protocol import ProviderPaymentCommand
from backend.app.schemas.razorpay import (
    RazorpayConfigurationStatus,
    RazorpayOrderEntity,
    RazorpayOrderRequest,
    RazorpayProviderCallResult,
    RazorpayProviderOutcome,
)


RAZORPAY_API_BASE_URL = "https://api.razorpay.com"
RAZORPAY_REQUEST_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class RazorpayTestCredentials:
    key_id: str
    key_secret: str
    webhook_secret: str

    @classmethod
    def from_environment(cls) -> "RazorpayTestCredentials":
        key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()

        missing = [
            name
            for name, value in (
                ("RAZORPAY_KEY_ID", key_id),
                ("RAZORPAY_KEY_SECRET", key_secret),
                ("RAZORPAY_WEBHOOK_SECRET", webhook_secret),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "Razorpay Test Mode is not configured. Missing: "
                + ", ".join(missing)
            )

        if not key_id.startswith("rzp_test_"):
            raise ValueError(
                "IntentPay accepts only Razorpay Test Mode key IDs."
            )

        return cls(
            key_id=key_id,
            key_secret=key_secret,
            webhook_secret=webhook_secret,
        )


def get_razorpay_configuration_status() -> RazorpayConfigurationStatus:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
    values = {
        "RAZORPAY_KEY_ID": key_id,
        "RAZORPAY_KEY_SECRET": key_secret,
        "RAZORPAY_WEBHOOK_SECRET": webhook_secret,
    }
    missing = [name for name, value in values.items() if not value]
    test_key = key_id.startswith("rzp_test_")
    configured = not missing and test_key

    if key_id and not test_key:
        message = (
            "Configuration was rejected because only rzp_test_ key IDs "
            "are permitted."
        )
    elif missing:
        message = (
            "Razorpay Test Mode is disabled until all required environment "
            "variables are configured."
        )
    else:
        message = "Razorpay Test Mode credentials are configured."

    key_id_hint = None
    if key_id:
        key_id_hint = f"{key_id[:9]}...{key_id[-4:]}"

    return RazorpayConfigurationStatus(
        configured=configured,
        key_id_hint=key_id_hint,
        missing_fields=missing,
        message=message,
    )


def build_razorpay_receipt(
    command: ProviderPaymentCommand,
) -> str:
    return build_razorpay_receipt_from_values(
        intent_id=command.context.intent_id,
        idempotency_key=command.idempotency_key,
        authorized_amount=command.authorized_amount,
    )


def build_razorpay_receipt_from_values(
    intent_id: str,
    idempotency_key: str,
    authorized_amount: int,
) -> str:
    source = (
        f"{intent_id}:"
        f"{idempotency_key}:"
        f"{authorized_amount}"
    )
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    return f"ip_{digest}"


def build_razorpay_order_request(
    command: ProviderPaymentCommand,
    local_payment_id: str,
) -> RazorpayOrderRequest:
    return RazorpayOrderRequest(
        amount=command.authorized_amount * 100,
        receipt=build_razorpay_receipt(command),
        notes={
            "intentpay_payment_id": local_payment_id,
            "intent_id": command.context.intent_id,
            "correlation_id": str(command.context.correlation_id),
            "product_id": command.purchase.product_id,
        },
    )


def verify_webhook_signature(
    raw_body: bytes,
    received_signature: str,
    webhook_secret: str,
) -> bool:
    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, received_signature)


def verify_checkout_signature(
    provider_order_id: str,
    provider_payment_id: str,
    received_signature: str,
    key_secret: str,
) -> bool:
    message = f"{provider_order_id}|{provider_payment_id}".encode("utf-8")
    expected_signature = hmac.new(
        key_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, received_signature)


class RazorpayTestClient:
    def __init__(
        self,
        credentials: RazorpayTestCredentials,
        http_client: httpx.Client | None = None,
    ):
        if not credentials.key_id.startswith("rzp_test_"):
            raise ValueError("Only Razorpay Test Mode credentials are allowed.")
        self.credentials = credentials
        self.http_client = http_client

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        kwargs.setdefault(
            "auth",
            (self.credentials.key_id, self.credentials.key_secret),
        )
        if self.http_client is not None:
            return self.http_client.request(method, path, **kwargs)

        return httpx.request(
            method,
            f"{RAZORPAY_API_BASE_URL}{path}",
            timeout=RAZORPAY_REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )

    def create_order(
        self,
        order_request: RazorpayOrderRequest,
    ) -> RazorpayProviderCallResult:
        try:
            response = self._request(
                "POST",
                "/v1/orders",
                json=order_request.model_dump(mode="json"),
            )
        except httpx.RequestError:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_ORDER_RESULT_UNKNOWN",
                message=(
                    "The Razorpay order request did not return a reliable "
                    "response. The local payment requires reconciliation."
                ),
            )

        if response.status_code >= 500:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_ORDER_RESULT_UNKNOWN",
                message=(
                    "Razorpay returned a server error after order submission. "
                    "The result is treated as unknown."
                ),
                provider_http_status=response.status_code,
            )

        if response.status_code >= 400:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.REJECTED,
                reason_code="RAZORPAY_ORDER_REJECTED",
                message="Razorpay rejected the test order request.",
                provider_http_status=response.status_code,
            )

        try:
            order = RazorpayOrderEntity.model_validate(response.json())
        except (ValueError, ValidationError):
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_ORDER_RESPONSE_INVALID",
                message=(
                    "Razorpay returned an invalid order response. The local "
                    "payment requires reconciliation."
                ),
                provider_http_status=response.status_code,
            )

        return RazorpayProviderCallResult(
            outcome=RazorpayProviderOutcome.SUCCESS,
            reason_code="RAZORPAY_TEST_ORDER_CREATED",
            message="A Razorpay Test Mode order was created.",
            order=order,
            provider_http_status=response.status_code,
        )

    def fetch_order(
        self,
        provider_order_id: str,
    ) -> RazorpayProviderCallResult:
        try:
            response = self._request(
                "GET",
                f"/v1/orders/{provider_order_id}",
            )
        except httpx.RequestError:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_RECONCILIATION_UNAVAILABLE",
                message="Razorpay order status could not be fetched.",
            )

        if response.status_code >= 500:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_RECONCILIATION_UNAVAILABLE",
                message="Razorpay order status is temporarily unavailable.",
                provider_http_status=response.status_code,
            )

        if response.status_code >= 400:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.REJECTED,
                reason_code="RAZORPAY_ORDER_FETCH_REJECTED",
                message="Razorpay rejected the order status request.",
                provider_http_status=response.status_code,
            )

        try:
            order = RazorpayOrderEntity.model_validate(response.json())
        except (ValueError, ValidationError):
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_ORDER_RESPONSE_INVALID",
                message="Razorpay returned an invalid order response.",
                provider_http_status=response.status_code,
            )

        return RazorpayProviderCallResult(
            outcome=RazorpayProviderOutcome.SUCCESS,
            reason_code="RAZORPAY_ORDER_FETCHED",
            message="Razorpay Test Mode order status was fetched.",
            order=order,
            provider_http_status=response.status_code,
        )

    def find_order_by_receipt(
        self,
        receipt: str,
    ) -> RazorpayProviderCallResult:
        try:
            response = self._request(
                "GET",
                "/v1/orders",
                params={"receipt": receipt, "count": 100},
            )
        except httpx.RequestError:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_RECONCILIATION_UNAVAILABLE",
                message="Razorpay receipt lookup could not be completed.",
            )

        if response.status_code >= 500:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_RECONCILIATION_UNAVAILABLE",
                message="Razorpay receipt lookup is temporarily unavailable.",
                provider_http_status=response.status_code,
            )
        if response.status_code >= 400:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.REJECTED,
                reason_code="RAZORPAY_RECEIPT_LOOKUP_REJECTED",
                message="Razorpay rejected the receipt lookup request.",
                provider_http_status=response.status_code,
            )

        try:
            raw_items = response.json()["items"]
            matching_orders = [
                RazorpayOrderEntity.model_validate(item)
                for item in raw_items
                if item.get("receipt") == receipt
            ]
        except (KeyError, TypeError, ValueError, ValidationError):
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_ORDER_RESPONSE_INVALID",
                message="Razorpay returned an invalid receipt lookup response.",
                provider_http_status=response.status_code,
            )

        if not matching_orders:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.REJECTED,
                reason_code="RAZORPAY_ORDER_NOT_FOUND_BY_RECEIPT",
                message="No Razorpay order matched the deterministic receipt.",
                provider_http_status=response.status_code,
            )
        if len(matching_orders) != 1:
            return RazorpayProviderCallResult(
                outcome=RazorpayProviderOutcome.UNCERTAIN,
                reason_code="RAZORPAY_RECEIPT_NOT_UNIQUE",
                message="Multiple Razorpay orders matched one receipt.",
                provider_http_status=response.status_code,
            )

        return RazorpayProviderCallResult(
            outcome=RazorpayProviderOutcome.SUCCESS,
            reason_code="RAZORPAY_ORDER_FOUND_BY_RECEIPT",
            message="Razorpay order was recovered using its receipt.",
            order=matching_orders[0],
            provider_http_status=response.status_code,
        )
