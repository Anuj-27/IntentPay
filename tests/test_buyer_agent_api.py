from backend.app.schemas.decision import DecisionType


BASE_INTENT = {
    "product_category": "headphones",
    "max_budget": 5000,
    "quantity": 1,
    "brand": "Sony",
    "brand_preference": "EXACT",
    "subscription_allowed": False,
    "autonomous_selection_allowed": False,
    "priority": "BEST_VALUE",
    "preferred_features": [
        "ANC",
        "fast charging",
    ],
}


def create_intent(
    client,
    intent: dict | None = None,
) -> str:
    response = client.post(
        "/intents",
        json=intent or BASE_INTENT,
    )

    assert response.status_code == 201

    return response.json()["intent_id"]


def test_buyer_agent_rejects_unknown_intent(client):
    response = client.post(
        "/intents/unknown-intent/buyer-agent"
    )

    assert response.status_code == 404
    assert (
        response.json()["detail"]["reason_code"]
        == "INTENT_NOT_FOUND"
    )


def test_buyer_agent_reasks_without_user_selection(client):
    intent_id = create_intent(client)

    response = client.post(
        f"/intents/{intent_id}/buyer-agent"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["decision"] == DecisionType.REASK
    assert (
        body["reason_code"]
        == "MEANINGFUL_PRICE_VALUE_TRADEOFF"
    )

    assert body["recommended_product"]["product_id"] == "PROD-002"
    assert body["selected_product"] is None
    assert body["proposed_purchase"] is None

    audit_response = client.get(
        f"/audit/{intent_id}"
    )

    assert audit_response.status_code == 200

    buyer_logs = [
        log
        for log in audit_response.json()["logs"]
        if log["event_type"] == "BUYER_AGENT_DECISION"
    ]

    assert len(buyer_logs) == 1
    assert buyer_logs[0]["decision"] == "REASK"
    assert buyer_logs[0]["details"]["proposal_created"] is False


def test_buyer_agent_uses_confirmed_product(client):
    intent_id = create_intent(client)

    selection_response = client.post(
        f"/intents/{intent_id}/selection",
        json={
            "product_id": "PROD-001",
        },
    )

    assert selection_response.status_code == 200

    response = client.post(
        f"/intents/{intent_id}/buyer-agent"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["decision"] == DecisionType.ALLOW
    assert (
        body["reason_code"]
        == "PURCHASE_PROPOSAL_CREATED"
    )

    assert (
        body["proposed_purchase"]["product_id"]
        == "PROD-001"
    )

    assert body["recommended_product"]["product_id"] == "PROD-002"
    assert body["selected_product"]["product_id"] == "PROD-001"

    assert body["proposed_purchase"]["total_amount"] == 3200


def test_autonomous_buyer_agent_selects_top_product(client):
    autonomous_intent = {
        **BASE_INTENT,
        "autonomous_selection_allowed": True,
    }

    intent_id = create_intent(
        client,
        autonomous_intent,
    )

    response = client.post(
        f"/intents/{intent_id}/buyer-agent"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["decision"] == DecisionType.ALLOW
    assert (
        body["reason_code"]
        == "PURCHASE_PROPOSAL_CREATED"
    )

    assert (
        body["proposed_purchase"]["product_id"]
        == "PROD-002"
    )

    assert body["selected_product"]["product_id"] == "PROD-002"

    assert body["proposed_purchase"]["unit_price"] == 4800
    assert body["proposed_purchase"]["total_amount"] == 4800
    assert body["proposed_purchase"]["subscription"] is False
