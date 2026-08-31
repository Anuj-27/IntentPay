import hashlib
import hmac
import json

import httpx
import pytest

from backend.app.main import app, get_razorpay_test_client
from backend.app.services.razorpay_adapter import (
    RazorpayTestClient,
    RazorpayTestCredentials,
)


TEST_CREDENTIALS = RazorpayTestCredentials(
    key_id="rzp_test_intentpay123",
    key_secret="test-key-secret",
    webhook_secret="test-webhook-secret",
)

INTENT = {
    "product_category": "headphones",
    "max_budget": 3500,
    "brand": "Sony",
    "brand_preference": "EXACT",
    "autonomous_selection_allowed": False,
}

PURCHASE = {
    "product_id": "PROD-001",
    "quantity": 1,
    "unit_price": 3200,
    "total_amount": 3200,
    "subscription": False,
}


def create_selected_intent(client):
    intent_id = client.post("/intents", json=INTENT).json()["intent_id"]
    response = client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    assert response.status_code == 200
    return intent_id


def payment_request(intent_id, key="razorpay-api-test-key"):
    return {
        "intent_id": intent_id,
        "purchase": PURCHASE,
        "idempotency_key": key,
    }


def order_payload(request_json, *, status="created", amount=None):
    return {
        "id": "order_intentpay_test",
        "entity": "order",
        "amount": amount or request_json["amount"],
        "amount_paid": request_json["amount"] if status == "paid" else 0,
        "amount_due": 0 if status == "paid" else request_json["amount"],
        "currency": request_json["currency"],
        "receipt": request_json["receipt"],
        "status": status,
        "attempts": 1 if status != "created" else 0,
    }


def install_adapter(handler):
    http_client = httpx.Client(
        base_url="https://api.razorpay.com",
        transport=httpx.MockTransport(handler),
    )
    adapter = RazorpayTestClient(TEST_CREDENTIALS, http_client)
    app.dependency_overrides[get_razorpay_test_client] = lambda: adapter
    return adapter


def create_order_with_adapter(client, handler, key="razorpay-api-test-key"):
    install_adapter(handler)
    intent_id = create_selected_intent(client)
    response = client.post(
        "/payments/razorpay-test/orders",
        json=payment_request(intent_id, key),
    )
    return response


def signed_webhook_request(client, payload, event_id, signature=None):
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    valid_signature = hmac.new(
        TEST_CREDENTIALS.webhook_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/razorpay",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature or valid_signature,
            "X-Razorpay-Event-Id": event_id,
        },
    )


def webhook_payload(event_type, *, amount=320000):
    status = event_type.split(".")[1]
    return {
        "entity": "event",
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_intentpay_test",
                    "entity": "payment",
                    "amount": amount,
                    "currency": "INR",
                    "status": status,
                    "order_id": "order_intentpay_test",
                },
            },
        },
    }


def test_configuration_is_fail_closed_without_credentials(client, monkeypatch):
    for name in (
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    status = client.get("/payments/razorpay-test/configuration")
    assert status.status_code == 200
    assert status.json()["configured"] is False
    assert status.json()["test_mode_only"] is True

    intent_id = create_selected_intent(client)
    response = client.post(
        "/payments/razorpay-test/orders",
        json=payment_request(intent_id),
    )
    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == "RAZORPAY_TEST_NOT_CONFIGURED"


def test_trust_gate_blocks_before_provider_configuration_is_required(client):
    intent_id = client.post(
        "/intents",
        json={**INTENT, "max_budget": 3000},
    ).json()["intent_id"]

    response = client.post(
        "/payments/razorpay-test/orders",
        json=payment_request(intent_id),
    )

    assert response.status_code == 200
    assert response.json()["payment_created"] is False
    assert response.json()["final_decision"]["decision"] != "ALLOW"


def test_verified_order_is_created_in_paise_and_replay_is_local(client):
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json=order_payload(body))

    install_adapter(handler)
    intent_id = create_selected_intent(client)
    request_body = payment_request(intent_id)

    first = client.post("/payments/razorpay-test/orders", json=request_body)
    replay = client.post("/payments/razorpay-test/orders", json=request_body)

    assert first.status_code == 200
    body = first.json()
    assert body["payment_created"] is True
    assert body["reason_code"] == "RAZORPAY_TEST_ORDER_CREATED"
    assert body["order_request"]["amount"] == 320000
    assert body["provider_order"]["status"] == "created"
    assert body["order_verification"]["verified"] is True
    assert body["provider_verification"]["verified"] is True
    assert body["payment_result"]["payment"]["status"] == "PENDING"
    assert body["checkout_options"]["key"].startswith("rzp_test_")
    assert replay.json()["payment_created"] is False
    assert replay.json()["reason_code"] == "RAZORPAY_ORDER_IDEMPOTENT_REPLAY"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("provider_behavior", "expected_status", "expected_reason"),
    [
        ("timeout", "UNKNOWN", "RAZORPAY_ORDER_RESULT_UNKNOWN"),
        ("reject", "FAILED", "RAZORPAY_ORDER_REJECTED"),
        ("tamper", "UNKNOWN", "RAZORPAY_ORDER_VERIFICATION_FAILED"),
    ],
)
def test_provider_failures_are_fail_closed(
    client,
    provider_behavior,
    expected_status,
    expected_reason,
):
    def handler(request):
        if provider_behavior == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if provider_behavior == "reject":
            return httpx.Response(400, json={"error": {"code": "BAD_REQUEST"}})
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json=order_payload(body, amount=body["amount"] + 100),
        )

    response = create_order_with_adapter(
        client,
        handler,
        key=f"razorpay-{provider_behavior}-key",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reason_code"] == expected_reason
    assert body["payment_result"]["payment"]["status"] == expected_status
    assert body["checkout_options"] is None


def test_checkout_signature_is_verified_without_marking_payment_captured(client):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json=order_payload(body))

    response = create_order_with_adapter(client, handler)
    body = response.json()
    local_payment_id = body["payment_result"]["payment"]["payment_id"]
    provider_order_id = body["provider_order"]["id"]
    provider_payment_id = "pay_intentpay_test"
    signature = hmac.new(
        TEST_CREDENTIALS.key_secret.encode(),
        f"{provider_order_id}|{provider_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    verified = client.post(
        f"/payments/{local_payment_id}/razorpay-test/verify-checkout",
        json={
            "razorpay_order_id": provider_order_id,
            "razorpay_payment_id": provider_payment_id,
            "razorpay_signature": signature,
        },
    )

    assert verified.status_code == 200
    assert verified.json()["verified"] is True
    assert verified.json()["awaiting_captured_webhook"] is True


def test_signed_captured_webhook_updates_once_and_rejects_tampering(client):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json=order_payload(body))

    order_response = create_order_with_adapter(client, handler)
    local_payment_id = order_response.json()["payment_result"]["payment"][
        "payment_id"
    ]
    payload = webhook_payload("payment.captured")

    captured = signed_webhook_request(client, payload, "rzp-event-captured")
    duplicate = signed_webhook_request(client, payload, "rzp-event-captured")
    invalid = signed_webhook_request(
        client,
        payload,
        "rzp-event-invalid",
        signature="not-valid",
    )

    assert captured.status_code == 200
    assert captured.json()["processed"] is True
    assert captured.json()["payment"]["status"] == "CAPTURED"
    assert captured.json()["payment_id"] == local_payment_id
    assert duplicate.status_code == 200
    assert duplicate.json()["processed"] is False
    assert duplicate.json()["reason_code"] == "DUPLICATE_WEBHOOK_EVENT"
    assert invalid.status_code == 401


def test_signed_webhook_amount_mismatch_is_rejected(client):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json=order_payload(body))

    create_order_with_adapter(client, handler)
    response = signed_webhook_request(
        client,
        webhook_payload("payment.captured", amount=999900),
        "rzp-event-amount-mismatch",
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]["reason_code"]
        == "RAZORPAY_WEBHOOK_TRANSACTION_MISMATCH"
    )


def test_out_of_order_authorized_event_is_ignored_after_capture(client):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json=order_payload(body))

    create_order_with_adapter(client, handler)
    captured = signed_webhook_request(
        client,
        webhook_payload("payment.captured"),
        "rzp-event-first-captured",
    )
    authorized = signed_webhook_request(
        client,
        webhook_payload("payment.authorized"),
        "rzp-event-late-authorized",
    )

    assert captured.status_code == 200
    assert authorized.status_code == 200
    assert authorized.json()["processed"] is False
    assert authorized.json()["reason_code"] == "STALE_PROVIDER_STATUS"
    assert authorized.json()["payment"]["status"] == "CAPTURED"


def test_failed_attempt_does_not_close_order_before_successful_retry(client):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json=order_payload(body))

    create_order_with_adapter(client, handler)
    failed = signed_webhook_request(
        client,
        webhook_payload("payment.failed"),
        "rzp-event-failed-attempt",
    )
    captured = signed_webhook_request(
        client,
        webhook_payload("payment.captured"),
        "rzp-event-retry-captured",
    )

    assert failed.status_code == 200
    assert failed.json()["reason_code"] == "RAZORPAY_PAYMENT_ATTEMPT_FAILED"
    assert failed.json()["payment"]["status"] == "PENDING"
    assert captured.status_code == 200
    assert captured.json()["payment"]["status"] == "CAPTURED"


def test_reconciliation_maps_paid_order_to_captured(client):
    created_request = None

    def handler(request):
        nonlocal created_request
        if request.method == "POST":
            created_request = json.loads(request.content)
            return httpx.Response(200, json=order_payload(created_request))
        return httpx.Response(
            200,
            json=order_payload(created_request, status="paid"),
        )

    order_response = create_order_with_adapter(client, handler)
    local_payment_id = order_response.json()["payment_result"]["payment"][
        "payment_id"
    ]

    reconciled = client.post(
        f"/payments/{local_payment_id}/razorpay-test/reconcile"
    )

    assert reconciled.status_code == 200
    assert reconciled.json()["success"] is True
    assert reconciled.json()["payment"]["status"] == "CAPTURED"
    assert reconciled.json()["provider_order"]["status"] == "paid"


def test_timeout_reconciliation_recovers_order_by_receipt(client):
    submitted_order = None

    def handler(request):
        nonlocal submitted_order
        if request.method == "POST":
            submitted_order = json.loads(request.content)
            raise httpx.ReadTimeout("timeout", request=request)
        recovered = order_payload(submitted_order, status="paid")
        return httpx.Response(
            200,
            json={
                "entity": "collection",
                "count": 1,
                "items": [recovered],
            },
        )

    order_response = create_order_with_adapter(
        client,
        handler,
        key="razorpay-receipt-recovery-key",
    )
    assert order_response.json()["payment_result"]["payment"]["status"] == "UNKNOWN"
    local_payment_id = order_response.json()["payment_result"]["payment"][
        "payment_id"
    ]

    reconciled = client.post(
        f"/payments/{local_payment_id}/razorpay-test/reconcile"
    )

    assert reconciled.status_code == 200
    assert reconciled.json()["success"] is True
    assert reconciled.json()["payment"]["status"] == "CAPTURED"
    assert (
        reconciled.json()["payment"]["provider_order_id"]
        == "order_intentpay_test"
    )


def test_razorpay_routes_are_typed_in_openapi(client):
    spec = client.get("/openapi.json").json()
    required = {
        "/payments/razorpay-test/configuration",
        "/payments/razorpay-test/orders",
        "/payments/{payment_id}/razorpay-test/verify-checkout",
        "/payments/{payment_id}/razorpay-test/reconcile",
        "/webhooks/razorpay",
    }

    assert required <= set(spec["paths"])
