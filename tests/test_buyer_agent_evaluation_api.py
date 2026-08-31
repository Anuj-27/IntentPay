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


def test_evaluation_reasks_when_selection_is_missing(client):
    intent_id = create_intent(client)

    response = client.post(
        f"/intents/{intent_id}/buyer-agent/evaluate"
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["buyer_agent"]["decision"]
        == DecisionType.REASK
    )

    assert body["buyer_agent"]["proposed_purchase"] is None

    # Verification and merchant policy must not run
    # when no proposed transaction exists.
    assert body["verification"] is None
    assert body["intent_decision"] is None
    assert body["merchant_policy"] is None

    assert (
        body["final_decision"]["decision"]
        == DecisionType.REASK
    )

    assert body["ready_for_payment"] is False


def test_reask_evaluation_audits_without_running_trust_gate(client):
    intent_id = create_intent(client)

    response = client.post(
        f"/intents/{intent_id}/buyer-agent/evaluate"
    )

    assert response.status_code == 200

    audit_response = client.get(
        f"/audit/{intent_id}"
    )

    assert audit_response.status_code == 200

    logs = audit_response.json()["logs"]
    buyer_logs = [
        log
        for log in logs
        if log["event_type"] == "BUYER_AGENT_DECISION"
    ]
    trust_logs = [
        log
        for log in logs
        if log["event_type"] == "TRUST_GATE_PREVIEW_DECISION"
    ]

    assert len(buyer_logs) == 1
    assert buyer_logs[0]["decision"] == "REASK"
    assert buyer_logs[0]["details"]["proposal_created"] is False
    assert trust_logs == []


def test_confirmed_low_value_product_passes_trust_gate(client):
    intent_id = create_intent(client)

    selection_response = client.post(
        f"/intents/{intent_id}/selection",
        json={
            "product_id": "PROD-001",
        },
    )

    assert selection_response.status_code == 200

    response = client.post(
        f"/intents/{intent_id}/buyer-agent/evaluate"
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["buyer_agent"]["decision"]
        == DecisionType.ALLOW
    )

    assert (
        body["buyer_agent"]["proposed_purchase"]["product_id"]
        == "PROD-001"
    )

    assert body["verification"]["verified"] is True
    assert body["verification"]["expected_total"] == 3200

    assert (
        body["intent_decision"]["decision"]
        == DecisionType.ALLOW
    )

    assert body["merchant_policy"]["status"] == "APPROVED"

    assert (
        body["final_decision"]["decision"]
        == DecisionType.ALLOW
    )

    assert body["ready_for_payment"] is True


def test_autonomous_high_value_product_requires_merchant_review(
    client,
):
    autonomous_intent = {
        **BASE_INTENT,
        "autonomous_selection_allowed": True,
    }

    intent_id = create_intent(
        client,
        autonomous_intent,
    )

    response = client.post(
        f"/intents/{intent_id}/buyer-agent/evaluate"
    )

    assert response.status_code == 200

    body = response.json()

    # Buyer Agent is allowed to propose PROD-002.
    assert (
        body["buyer_agent"]["decision"]
        == DecisionType.ALLOW
    )

    assert (
        body["buyer_agent"]["proposed_purchase"]["product_id"]
        == "PROD-002"
    )

    assert body["verification"]["verified"] is True
    assert body["verification"]["expected_total"] == 4800

    # Merchant threshold is ₹3,500.
    assert (
        body["merchant_policy"]["status"]
        == "REVIEW_REQUIRED"
    )

    assert (
        body["merchant_policy"]["reason_code"]
        == "MERCHANT_APPROVAL_THRESHOLD"
    )

    # User authorization passed, but merchant approval is required.
    assert (
        body["final_decision"]["decision"]
        == DecisionType.ESCALATE
    )

    assert body["ready_for_payment"] is False


def test_escalated_evaluation_audit_is_not_ready_for_payment(client):
    autonomous_intent = {
        **BASE_INTENT,
        "autonomous_selection_allowed": True,
    }
    intent_id = create_intent(
        client,
        autonomous_intent,
    )

    response = client.post(
        f"/intents/{intent_id}/buyer-agent/evaluate"
    )

    assert response.status_code == 200

    audit_response = client.get(
        f"/audit/{intent_id}"
    )

    trust_log = next(
        log
        for log in audit_response.json()["logs"]
        if log["event_type"] == "TRUST_GATE_PREVIEW_DECISION"
    )

    assert trust_log["decision"] == "ESCALATE"
    assert (
        trust_log["details"]["merchant_policy_reason"]
        == "MERCHANT_APPROVAL_THRESHOLD"
    )
    assert trust_log["details"]["ready_for_payment"] is False


def test_buyer_agent_evaluation_is_audited(client):
    intent_id = create_intent(client)

    selection_response = client.post(
        f"/intents/{intent_id}/selection",
        json={
            "product_id": "PROD-001",
        },
    )

    assert selection_response.status_code == 200

    evaluation_response = client.post(
        f"/intents/{intent_id}/buyer-agent/evaluate"
    )

    assert evaluation_response.status_code == 200

    audit_response = client.get(
        f"/audit/{intent_id}"
    )

    assert audit_response.status_code == 200

    logs = audit_response.json()["logs"]

    event_types = {
        log["event_type"]
        for log in logs
    }

    assert "BUYER_AGENT_DECISION" in event_types
    assert "TRUST_GATE_PREVIEW_DECISION" in event_types

    buyer_log = next(
        log
        for log in logs
        if log["event_type"] == "BUYER_AGENT_DECISION"
    )

    assert buyer_log["decision"] == "ALLOW"
    assert (
        buyer_log["reason_code"]
        == "PURCHASE_PROPOSAL_CREATED"
    )

    assert (
        buyer_log["details"]["proposed_product_id"]
        == "PROD-001"
    )

    trust_log = next(
        log
        for log in logs
        if log["event_type"]
        == "TRUST_GATE_PREVIEW_DECISION"
    )

    assert trust_log["decision"] == "ALLOW"
    assert trust_log["details"]["verified"] is True
    assert trust_log["details"]["expected_total"] == 3200
    assert trust_log["details"]["ready_for_payment"] is True
