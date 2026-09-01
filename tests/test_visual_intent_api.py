import base64
import json

import httpx

from backend.app.main import (
    app,
    get_razorpay_test_client,
    get_visual_intent_analyzer,
)
from backend.app.schemas.visual_intent import VisualProductCandidate
from backend.app.services.razorpay_adapter import (
    RazorpayTestClient,
    RazorpayTestCredentials,
)


PNG_BASE64 = base64.b64encode(
    b"\x89PNG\r\n\x1a\nintentpay-test"
).decode()


def visual_request(**updates):
    request = {
        "image_base64": PNG_BASE64,
        "media_type": "image/png",
        "quantity": 1,
    }
    request.update(updates)
    return request


def install_candidate(candidate: VisualProductCandidate):
    app.dependency_overrides[get_visual_intent_analyzer] = lambda: (
        lambda request: candidate
    )


def pixel_candidate(**updates):
    values = {
        "product_name": "Google Pixel 9a 128GB",
        "category": "smartphone",
        "brand": "Google",
        "model": "Pixel 9a",
        "variant": "8GB/128GB",
        "displayed_price": 47999,
        "currency": "INR",
        "merchant_name": "DemoTech",
        "merchant_domain": "demotech.example",
        "visible_features": ["5G"],
        "confidence": 0.96,
    }
    values.update(updates)
    return VisualProductCandidate(**values)


def test_screenshot_price_is_not_treated_as_budget(client):
    install_candidate(pixel_candidate())

    response = client.post(
        "/visual-intents/analyze",
        json=visual_request(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reason_code"] == "MAX_BUDGET_REQUIRED"
    assert body["max_budget"] is None
    assert body["selected_match"]["product"]["product_id"] == "TECH-PHONE-001"
    assert body["requires_user_confirmation"] is True
    assert body["image_retained"] is False


def test_verified_visual_match_is_ready_only_for_confirmation(client):
    install_candidate(pixel_candidate())

    response = client.post(
        "/visual-intents/analyze",
        json=visual_request(max_budget=52000),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY_FOR_CONFIRMATION"
    assert body["reason_code"] == "PRODUCT_CONFIRMATION_REQUIRED"
    assert body["selected_match"]["merchant_id"] == "MERCHANT-002"


def test_unapproved_visible_domain_fails_closed(client):
    install_candidate(pixel_candidate(merchant_domain="untrusted-shop.example"))

    response = client.post(
        "/visual-intents/analyze",
        json=visual_request(max_budget=52000),
    )

    assert response.status_code == 200
    assert response.json()["reason_code"] == "MERCHANT_NOT_SUPPORTED"
    assert response.json()["selected_match"] is None


def test_low_confidence_screenshot_requires_a_clearer_image(client):
    install_candidate(pixel_candidate(confidence=0.42))

    response = client.post(
        "/visual-intents/analyze",
        json=visual_request(max_budget=52000),
    )

    assert response.status_code == 200
    assert response.json()["reason_code"] == "VISUAL_CONFIDENCE_TOO_LOW"


def test_verified_price_above_budget_requires_new_authorization(client):
    install_candidate(pixel_candidate())

    response = client.post(
        "/visual-intents/analyze",
        json=visual_request(max_budget=45000),
    )

    assert response.status_code == 200
    assert response.json()["reason_code"] == "BUDGET_EXCEEDED"


def test_invalid_image_is_rejected_before_analysis(client):
    install_candidate(pixel_candidate())

    response = client.post(
        "/visual-intents/analyze",
        json=visual_request(image_base64=base64.b64encode(b"not-a-png-image").decode()),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == "VISUAL_INTENT_INVALID"


def test_confirmed_visual_product_flows_to_razorpay_test_order(client):
    confirmation = client.post(
        "/visual-intents/confirm",
        json={
            "merchant_id": "MERCHANT-002",
            "product_id": "TECH-PHONE-001",
            "max_budget": 52000,
            "quantity": 1,
            "confirmed": True,
        },
    )

    assert confirmation.status_code == 201
    body = confirmation.json()
    assert body["evaluation"]["final_decision"]["decision"] == "ALLOW"
    assert body["razorpay_test_request"]["purchase"]["total_amount"] == 49999

    credentials = RazorpayTestCredentials(
        key_id="rzp_test_visualintent",
        key_secret="test-key-secret",
        webhook_secret="test-webhook-secret",
    )

    def handler(request):
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "order_visual_intent",
                "entity": "order",
                "amount": payload["amount"],
                "amount_paid": 0,
                "amount_due": payload["amount"],
                "currency": payload["currency"],
                "receipt": payload["receipt"],
                "status": "created",
                "attempts": 0,
            },
        )

    http_client = httpx.Client(
        base_url="https://api.razorpay.com",
        transport=httpx.MockTransport(handler),
    )
    adapter = RazorpayTestClient(credentials, http_client)
    app.dependency_overrides[get_razorpay_test_client] = lambda: adapter

    order = client.post(
        "/payments/razorpay-test/orders",
        json=body["razorpay_test_request"],
    )

    assert order.status_code == 200
    order_body = order.json()
    assert order_body["payment_created"] is True
    assert order_body["order_request"]["amount"] == 4_999_900
    assert order_body["checkout_options"]["order_id"] == "order_visual_intent"


def test_visual_confirmation_rejects_total_over_budget(client):
    response = client.post(
        "/visual-intents/confirm",
        json={
            "merchant_id": "MERCHANT-002",
            "product_id": "TECH-PHONE-001",
            "max_budget": 45000,
            "quantity": 1,
            "confirmed": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == "BUDGET_EXCEEDED"
