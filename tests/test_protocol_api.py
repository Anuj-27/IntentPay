from uuid import UUID


BASE_INTENT = {
    "merchant_id": "MERCHANT-001",
    "product_category": "headphones",
    "max_budget": 5000,
    "brand": "Sony",
    "brand_preference": "EXACT",
    "autonomous_selection_allowed": False,
}

PROD_001_PURCHASE = {
    "product_id": "PROD-001",
    "quantity": 1,
    "unit_price": 3200,
    "total_amount": 3200,
    "subscription": False,
}


def create_intent(client):
    response = client.post(
        "/intents",
        json=BASE_INTENT,
    )

    assert response.status_code == 201
    return response.json()


def test_protocol_manifest_is_explicit_about_support(client):
    response = client.get("/protocol/manifest")

    assert response.status_code == 200

    body = response.json()
    declarations = {
        declaration["protocol"]: declaration["status"]
        for declaration in body["external_protocols"]
    }

    assert body["protocol_version"] == "1.0"
    assert body["supported_payment_providers"] == [
        "INTERNAL_LEDGER",
        "RAZORPAY_TEST",
    ]
    assert declarations == {
        "UCP": "NOT_IMPLEMENTED",
        "AP2": "NOT_IMPLEMENTED",
        "ACP": "NOT_IMPLEMENTED",
        "X402": "NOT_IMPLEMENTED",
    }


def test_intent_receives_persisted_protocol_context(client):
    created = create_intent(client)
    context = created["protocol_context"]

    assert context["protocol_version"] == "1.0"
    assert context["intent_id"] == created["intent_id"]
    assert context["merchant_id"] == "MERCHANT-001"
    assert str(UUID(context["correlation_id"])) == context["correlation_id"]
    assert context["correlation_id"] != context["intent_id"]

    fetched = client.get(
        f"/intents/{created['intent_id']}/protocol-context"
    )

    assert fetched.status_code == 200
    assert fetched.json() == context


def test_unknown_intent_protocol_context_is_rejected(client):
    response = client.get(
        "/intents/UNKNOWN-INTENT/protocol-context"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["reason_code"] == "INTENT_NOT_FOUND"


def test_payment_exposes_verified_provider_boundary(client):
    created = create_intent(client)
    intent_id = created["intent_id"]
    correlation_id = created["protocol_context"]["correlation_id"]

    selection = client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )

    assert selection.status_code == 200

    payment = client.post(
        "/payments/create",
        json={
            "intent_id": intent_id,
            "purchase": PROD_001_PURCHASE,
            "idempotency_key": "protocol-api-key",
        },
    )

    assert payment.status_code == 200

    body = payment.json()
    assert body["payment_created"] is True
    assert body["protocol_context"]["correlation_id"] == correlation_id
    assert body["payment_command"]["context"]["correlation_id"] == correlation_id
    assert body["payment_command"]["provider"] == "INTERNAL_LEDGER"
    assert body["provider_result"]["provider"] == "INTERNAL_LEDGER"
    assert body["provider_result"]["product_id"] == "PROD-001"
    assert body["provider_verification"]["verified"] is True
    assert body["provider_verification"]["violations"] == []


def test_protocol_context_is_propagated_to_audit_events(client):
    created = create_intent(client)
    intent_id = created["intent_id"]
    context = created["protocol_context"]

    client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    client.post(
        "/payments/create",
        json={
            "intent_id": intent_id,
            "purchase": PROD_001_PURCHASE,
            "idempotency_key": "protocol-audit-key",
        },
    )

    payment_logs = client.get("/audit").json()["logs"]
    payment_created_log = next(
        log
        for log in payment_logs
        if (
            log["event_type"] == "PAYMENT_CREATED"
            and log["details"].get("correlation_id")
            == context["correlation_id"]
        )
    )
    payment_id = payment_created_log["entity_id"]

    client.patch(
        f"/payments/{payment_id}/status",
        json={"new_status": "PENDING"},
    )
    client.post(
        "/webhooks/payment",
        json={
            "event_id": "protocol-webhook-event",
            "payment_id": payment_id,
            "status": "CAPTURED",
        },
    )

    logs = client.get("/audit").json()["logs"]
    relevant_logs = [
        log
        for log in logs
        if (
            log["details"] is not None
            and log["details"].get("correlation_id")
            == context["correlation_id"]
        )
    ]
    event_types = {
        log["event_type"]
        for log in relevant_logs
    }

    assert {
        "INTENT_CREATED",
        "PRODUCT_SELECTION_CONFIRMED",
        "TRUST_GATE_DECISION",
        "PAYMENT_CREATED",
        "PAYMENT_STATUS_CHANGED",
        "WEBHOOK_APPLIED",
    }.issubset(event_types)
    assert all(
        log["details"]["protocol_version"] == "1.0"
        for log in relevant_logs
    )
