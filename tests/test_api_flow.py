from backend.app.schemas.decision import DecisionType
from backend.app.schemas.intent import IntentMandate


BASE_INTENT = {
    "product_category": "headphones",
    "max_budget": 5000,
    "quantity": 1,
    "brand": "Sony",
    "brand_preference": "EXACT",
    "subscription_allowed": False,
    "autonomous_selection_allowed": False,
    "priority": "BEST_VALUE",
    "preferred_features": ["ANC", "fast charging"],
}

PROD_001_PURCHASE = {
    "product_id": "PROD-001",
    "quantity": 1,
    "unit_price": 3200,
    "total_amount": 3200,
    "subscription": False,
}


def create_intent(client, intent=None):
    response = client.post("/intents", json=intent or BASE_INTENT)
    assert response.status_code == 201
    return response.json()["intent_id"]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_intent_is_persisted(client):
    intent_id = create_intent(client)

    response = client.get(f"/intents/{intent_id}")

    assert response.status_code == 200
    assert response.json()["intent"]["max_budget"] == 5000
    assert response.json()["selection_confirmed"] is False


def test_non_autonomous_purchase_requires_confirmed_selection(client):
    intent_id = create_intent(client)

    response = client.post(
        "/verify-purchase",
        json={"intent_id": intent_id, "purchase": PROD_001_PURCHASE},
    )

    body = response.json()
    assert body["final_decision"]["decision"] == DecisionType.REASK
    assert {
        violation["code"] for violation in body["verification"]["violations"]
    } == {"PRODUCT_SELECTION_NOT_CONFIRMED"}


def test_autonomous_purchase_does_not_require_selection(client):
    intent = {**BASE_INTENT, "autonomous_selection_allowed": True}
    intent_id = create_intent(client, intent)

    response = client.post(
        "/verify-purchase",
        json={"intent_id": intent_id, "purchase": PROD_001_PURCHASE},
    )

    assert response.json()["final_decision"]["decision"] == DecisionType.ALLOW


def test_confirmed_selection_allows_purchase(client):
    intent_id = create_intent(client)
    selection = client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    assert selection.status_code == 200

    response = client.post(
        "/verify-purchase",
        json={"intent_id": intent_id, "purchase": PROD_001_PURCHASE},
    )

    assert response.json()["final_decision"]["decision"] == DecisionType.ALLOW
    assert response.json()["merchant_policy"]["reason_code"] == "MERCHANT_POLICY_PASSED"


def test_wrong_product_after_confirmation_requires_reask(client):
    intent_id = create_intent(client)
    client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    premium_purchase = {
        "product_id": "PROD-002",
        "quantity": 1,
        "unit_price": 4800,
        "total_amount": 4800,
        "subscription": False,
    }

    response = client.post(
        "/verify-purchase",
        json={"intent_id": intent_id, "purchase": premium_purchase},
    )

    assert response.json()["final_decision"]["decision"] == DecisionType.REASK


def test_payment_request_cannot_replace_persisted_intent(client):
    response = client.post(
        "/payments/create",
        json={
            "intent": BASE_INTENT,
            "purchase": PROD_001_PURCHASE,
            "idempotency_key": "test-key-tamper",
        },
    )

    assert response.status_code == 422


def test_payment_idempotency_is_bound_to_intent(client):
    intent_id = create_intent(client)
    client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    request = {
        "intent_id": intent_id,
        "purchase": PROD_001_PURCHASE,
        "idempotency_key": "test-key-0001",
    }

    first = client.post("/payments/create", json=request)
    replay = client.post("/payments/create", json=request)

    assert first.status_code == 200
    assert first.json()["payment_created"] is True
    assert replay.json()["payment_created"] is False
    assert replay.json()["payment_result"]["reason_code"] == "IDEMPOTENT_REPLAY"
    assert first.json()["payment_result"]["payment"]["intent_id"] == intent_id


def test_unauthorized_subscription_is_blocked(client):
    intent_id = create_intent(client)
    client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    purchase = {**PROD_001_PURCHASE, "subscription": True}

    response = client.post(
        "/verify-purchase",
        json={"intent_id": intent_id, "purchase": purchase},
    )

    assert response.json()["final_decision"]["decision"] == DecisionType.BLOCK


def test_payment_state_and_webhook_replay(client):
    intent_id = create_intent(client)
    client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    payment_response = client.post(
        "/payments/create",
        json={
            "intent_id": intent_id,
            "purchase": PROD_001_PURCHASE,
            "idempotency_key": "test-key-0002",
        },
    )
    payment_id = payment_response.json()["payment_result"]["payment"]["payment_id"]

    pending = client.patch(
        f"/payments/{payment_id}/status",
        json={"new_status": "PENDING"},
    )
    webhook = client.post(
        "/webhooks/payment",
        json={
            "event_id": "event-0001",
            "payment_id": payment_id,
            "status": "CAPTURED",
        },
    )
    duplicate = client.post(
        "/webhooks/payment",
        json={
            "event_id": "event-0001",
            "payment_id": payment_id,
            "status": "CAPTURED",
        },
    )

    assert pending.json()["success"] is True
    assert webhook.json()["processed"] is True
    assert duplicate.json()["reason_code"] == "DUPLICATE_WEBHOOK_EVENT"


def test_llm_parser_is_exposed_without_real_api_call(client, monkeypatch):
    parsed_intent = IntentMandate(
        product_category="headphones",
        max_budget=5000,
    )
    monkeypatch.setattr(
        "backend.app.main.extract_intent_with_llm",
        lambda _message: parsed_intent,
    )

    response = client.post(
        "/intents/parse/llm",
        json={"message": "Buy headphones under ₹5,000"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "OPENAI_STRUCTURED_OUTPUT"
    assert response.json()["intent"]["max_budget"] == 5000
