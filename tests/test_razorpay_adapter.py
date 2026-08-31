import hashlib
import hmac

import httpx
import pytest
from types import SimpleNamespace
from uuid import uuid4

from backend.app.data.merchants import demo_merchant_contract
from backend.app.schemas.protocol import PaymentProvider
from backend.app.schemas.purchase import ProposedPurchase
from backend.app.schemas.razorpay import RazorpayOrderRequest
from backend.app.services.protocol_service import build_provider_payment_command
from backend.app.services.razorpay_adapter import (
    RazorpayTestClient,
    RazorpayTestCredentials,
    build_razorpay_order_request,
    verify_checkout_signature,
    verify_webhook_signature,
)


TEST_CREDENTIALS = RazorpayTestCredentials(
    key_id="rzp_test_intentpay123",
    key_secret="test-key-secret",
    webhook_secret="test-webhook-secret",
)


def test_live_razorpay_key_is_rejected():
    credentials = RazorpayTestCredentials(
        key_id="rzp_live_not_allowed",
        key_secret="secret",
        webhook_secret="webhook",
    )

    with pytest.raises(ValueError, match="Test Mode"):
        RazorpayTestClient(credentials)


def test_order_request_uses_paise_and_stable_receipt():
    intent_record = SimpleNamespace(
        intent_id="intent-adapter-test",
        correlation_id=str(uuid4()),
        protocol_version="1.0",
        mandate={
            "product_category": "headphones",
            "max_budget": 3500,
            "brand": "Sony",
            "brand_preference": "EXACT",
            "autonomous_selection_allowed": True,
        },
    )
    purchase = ProposedPurchase(
        product_id="PROD-001",
        quantity=1,
        unit_price=3200,
        total_amount=3200,
    )
    command = build_provider_payment_command(
        intent_record,
        purchase,
        "adapter-test-key",
        provider=PaymentProvider.RAZORPAY_TEST,
    )

    first = build_razorpay_order_request(command, "local-payment-id")
    second = build_razorpay_order_request(command, "local-payment-id")

    assert first.amount == 320000
    assert first.currency == demo_merchant_contract.merchant.currency
    assert first.receipt == second.receipt
    assert len(first.receipt) <= 40
    assert first.notes["intentpay_payment_id"] == "local-payment-id"


def test_signature_helpers_use_required_hmac_messages():
    raw_body = b'{"event":"payment.captured"}'
    webhook_signature = hmac.new(
        TEST_CREDENTIALS.webhook_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    checkout_signature = hmac.new(
        TEST_CREDENTIALS.key_secret.encode(),
        b"order_test|pay_test",
        hashlib.sha256,
    ).hexdigest()

    assert verify_webhook_signature(
        raw_body,
        webhook_signature,
        TEST_CREDENTIALS.webhook_secret,
    )
    assert verify_checkout_signature(
        "order_test",
        "pay_test",
        checkout_signature,
        TEST_CREDENTIALS.key_secret,
    )
    assert not verify_webhook_signature(
        raw_body,
        "invalid",
        TEST_CREDENTIALS.webhook_secret,
    )


def test_transport_timeout_is_reported_as_uncertain():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    http_client = httpx.Client(
        base_url="https://api.razorpay.com",
        transport=httpx.MockTransport(handler),
    )
    adapter = RazorpayTestClient(TEST_CREDENTIALS, http_client)

    result = adapter.create_order(RazorpayOrderRequest(
        amount=320000,
        currency="INR",
        receipt="ip_timeout",
        notes={},
    ))

    assert result.outcome == "UNCERTAIN"
    assert result.reason_code == "RAZORPAY_ORDER_RESULT_UNKNOWN"
