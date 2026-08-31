from copy import deepcopy

from backend.app.data.merchants import demo_merchant_contract
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.purchase import ProposedPurchase
from backend.app.services.buyer_agent import run_buyer_agent
from backend.app.services.privacy_service import (
    REDACTED_VALUE,
    redact_sensitive_data,
)
from backend.app.services.safety_service import (
    evaluate_recommendation_integrity,
)


def test_sensitive_audit_fields_are_recursively_redacted():
    original = {
        "authorization": "Bearer private",
        "nested": {
            "api-key": "secret-key",
            "safe": "visible",
            "items": [
                {"razorpay_signature": "signature"},
            ],
        },
    }
    untouched = deepcopy(original)

    redacted = redact_sensitive_data(original)

    assert redacted["authorization"] == REDACTED_VALUE
    assert redacted["nested"]["api-key"] == REDACTED_VALUE
    assert redacted["nested"]["safe"] == "visible"
    assert (
        redacted["nested"]["items"][0]["razorpay_signature"]
        == REDACTED_VALUE
    )
    assert original == untouched


def test_confirmed_cheapest_product_passes_integrity_check():
    intent = IntentMandate(
        product_category="headphones",
        max_budget=5000,
        brand="Sony",
        brand_preference="EXACT",
        autonomous_selection_allowed=False,
        preferred_features=["ANC", "fast charging"],
    )
    buyer_result = run_buyer_agent(
        intent,
        demo_merchant_contract,
        confirmed_product_id="PROD-001",
    )

    integrity = evaluate_recommendation_integrity(
        intent,
        buyer_result,
        confirmed_product_id="PROD-001",
    )

    assert integrity.verified is True
    assert integrity.cheapest_valid_product_id == "PROD-001"
    assert integrity.recommended_product_id == "PROD-002"
    assert integrity.recommended_price_premium == 1600


def test_integrity_guard_blocks_an_above_budget_tampered_proposal():
    intent = IntentMandate(
        product_category="headphones",
        max_budget=3500,
        brand="Sony",
        brand_preference="EXACT",
        autonomous_selection_allowed=True,
    )
    buyer_result = run_buyer_agent(intent, demo_merchant_contract)
    tampered_result = buyer_result.model_copy(update={
        "proposed_purchase": ProposedPurchase(
            product_id="PROD-001",
            quantity=1,
            unit_price=4000,
            total_amount=4000,
            subscription=False,
        ),
    })

    integrity = evaluate_recommendation_integrity(
        intent,
        tampered_result,
    )

    assert integrity.verified is False
    assert "ABOVE_BUDGET_PROPOSAL" in {
        violation.code
        for violation in integrity.violations
    }


def test_safety_manifest_and_security_headers_are_exposed(client):
    response = client.get("/safety/manifest")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"

    body = response.json()
    assert body["privacy_mode"] == "MINIMIZE_AND_REDACT"
    assert all(
        control["status"] == "ENFORCED"
        for control in body["controls"]
    )
    assert any(
        "authentication" in limitation.casefold()
        for limitation in body["limitations"]
    )


def test_idempotency_key_is_redacted_in_persisted_audit(client):
    intent = {
        "product_category": "headphones",
        "max_budget": 3500,
        "brand": "Sony",
        "brand_preference": "EXACT",
    }
    intent_id = client.post("/intents", json=intent).json()["intent_id"]
    client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )
    client.post(
        "/payments/create",
        json={
            "intent_id": intent_id,
            "purchase": {
                "product_id": "PROD-001",
                "quantity": 1,
                "unit_price": 3200,
                "total_amount": 3200,
                "subscription": False,
            },
            "idempotency_key": "never-log-this-key",
        },
    )

    logs = client.get(f"/audit/{intent_id}").json()["logs"]
    trust_log = next(
        log
        for log in logs
        if log["event_type"] == "TRUST_GATE_DECISION"
    )

    assert trust_log["details"]["idempotency_key"] == REDACTED_VALUE

