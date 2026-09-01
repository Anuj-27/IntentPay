from backend.app.data.merchants import (
    demo_merchant_contract,
    merchant_contracts,
)


BASE_INTENT = {
    "merchant_id": "MERCHANT-001",
    "product_category": "headphones",
    "max_budget": 5000,
    "brand": "Sony",
    "brand_preference": "EXACT",
    "autonomous_selection_allowed": True,
    "preferred_features": ["ANC", "fast charging"],
}

PROD_001_PURCHASE = {
    "product_id": "PROD-001",
    "quantity": 1,
    "unit_price": 3200,
    "total_amount": 3200,
    "subscription": False,
}


def test_merchant_discovery_returns_profile(client):
    response = client.get("/merchants")

    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 3
    assert body["merchants"][0]["merchant_id"] == "MERCHANT-001"
    assert body["merchants"][0]["display_name"] == "DemoStore"
    assert {
        merchant["merchant_id"]
        for merchant in body["merchants"]
    } == {"MERCHANT-001", "MERCHANT-002", "MERCHANT-003"}
    assert body["merchants"][0]["active"] is True


def test_agent_readable_contract_is_exposed(client):
    response = client.get("/merchants/MERCHANT-001")

    assert response.status_code == 200

    body = response.json()
    assert body["merchant"]["currency"] == "INR"
    assert body["merchant"]["contract_version"] == "1.0"
    assert body["merchant"]["policy"]["max_transaction_amount"] == 10000
    assert body["catalog"]["merchant_id"] == "MERCHANT-001"
    assert len(body["catalog"]["products"]) == 4


def test_capability_and_catalog_endpoints(client):
    capabilities = client.get(
        "/merchants/MERCHANT-001/capabilities"
    )
    catalog = client.get(
        "/merchants/MERCHANT-001/catalog"
    )

    assert capabilities.status_code == 200
    assert capabilities.json()["catalog_search"] is True
    assert capabilities.json()["inventory_check"] is True
    assert capabilities.json()["checkout"] is True

    assert catalog.status_code == 200
    assert catalog.json()["merchant_id"] == "MERCHANT-001"
    assert len(catalog.json()["products"]) == 4


def test_unknown_merchant_fails_with_structured_error(client):
    response = client.get("/merchants/UNKNOWN-MERCHANT")

    assert response.status_code == 404
    assert response.json()["detail"]["reason_code"] == "MERCHANT_NOT_FOUND"


def test_intent_is_bound_to_agent_readable_merchant(client):
    response = client.post(
        "/intents",
        json=BASE_INTENT,
    )

    assert response.status_code == 201
    assert response.json()["intent"]["merchant_id"] == "MERCHANT-001"

    intent_id = response.json()["intent_id"]
    buyer_response = client.post(
        f"/intents/{intent_id}/buyer-agent"
    )

    assert buyer_response.status_code == 200
    assert buyer_response.json()["merchant_id"] == "MERCHANT-001"


def test_unknown_merchant_intent_is_rejected(client):
    response = client.post(
        "/intents",
        json={
            **BASE_INTENT,
            "merchant_id": "UNKNOWN-MERCHANT",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["reason_code"] == "MERCHANT_NOT_FOUND"


def test_unavailable_catalog_capability_fails_closed(
    client,
    monkeypatch,
):
    contract = demo_merchant_contract.model_copy(deep=True)
    contract.merchant.capabilities.catalog_search = False
    monkeypatch.setitem(
        merchant_contracts,
        "MERCHANT-001",
        contract,
    )

    catalog_response = client.get(
        "/merchants/MERCHANT-001/catalog"
    )
    contract_response = client.get(
        "/merchants/MERCHANT-001"
    )
    intent_response = client.post(
        "/intents",
        json=BASE_INTENT,
    )

    expected_reason = "MERCHANT_CATALOG_SEARCH_UNAVAILABLE"

    assert catalog_response.status_code == 409
    assert (
        catalog_response.json()["detail"]["reason_code"]
        == expected_reason
    )
    assert contract_response.status_code == 409
    assert (
        contract_response.json()["detail"]["reason_code"]
        == expected_reason
    )
    assert intent_response.status_code == 409
    assert (
        intent_response.json()["detail"]["reason_code"]
        == expected_reason
    )


def test_direct_purchase_fails_when_checkout_is_unavailable(
    client,
    monkeypatch,
):
    contract = demo_merchant_contract.model_copy(deep=True)
    contract.merchant.capabilities.checkout = False
    monkeypatch.setitem(
        merchant_contracts,
        "MERCHANT-001",
        contract,
    )

    intent_response = client.post(
        "/intents",
        json=BASE_INTENT,
    )

    assert intent_response.status_code == 201

    verification_response = client.post(
        "/verify-purchase",
        json={
            "intent_id": intent_response.json()["intent_id"],
            "purchase": PROD_001_PURCHASE,
        },
    )

    assert verification_response.status_code == 200
    assert (
        verification_response.json()["merchant_policy"]["status"]
        == "REJECTED"
    )
    assert (
        verification_response.json()["final_decision"]["decision"]
        == "BLOCK"
    )
    assert (
        verification_response.json()["final_decision"]["reason_code"]
        == "MERCHANT_CHECKOUT_UNAVAILABLE"
    )
