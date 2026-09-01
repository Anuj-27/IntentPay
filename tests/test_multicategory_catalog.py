from backend.app.data.merchants import tech_merchant_contract
from backend.app.schemas.intent import IntentMandate
from backend.app.services.intent_extractor import extract_intent_from_text
from backend.app.services.product_filter import filter_products


def test_category_registry_exposes_five_demo_categories(client):
    response = client.get("/categories")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert {
        category["category_id"]
        for category in body["categories"]
    } == {"headphones", "smartphones", "laptops", "smartwatches", "cameras"}


def test_products_can_be_selected_by_merchant_and_category_alias(client):
    response = client.get(
        "/products",
        params={"merchant_id": "MERCHANT-002", "category": "phone"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == "MERCHANT-002"
    assert body["count"] == 2
    assert all(product["category"] == "smartphones" for product in body["products"])


def test_deterministic_parser_routes_category_to_approved_merchant():
    intent = extract_intent_from_text(
        "Buy a Samsung smartphone under INR 50000 with 5G."
    )

    assert intent.product_category == "smartphones"
    assert intent.merchant_id == "MERCHANT-002"
    assert intent.max_budget == 50000
    assert intent.brand == "Samsung"
    assert "5G" in intent.preferred_features


def test_direct_intent_normalizes_a_supported_category_alias():
    intent = IntentMandate(
        merchant_id="MERCHANT-002",
        product_category="phone",
        max_budget=50000,
    )

    assert intent.product_category == "smartphones"


def test_required_attributes_are_enforced_generically():
    intent = IntentMandate(
        merchant_id="MERCHANT-002",
        product_category="laptops",
        max_budget=70000,
        required_attributes={"processor": "AMD Ryzen 7", "ram_gb": 16},
    )

    allowed, rejected = filter_products(
        intent,
        tech_merchant_contract.catalog.products,
    )

    assert [product.product_id for product in allowed] == ["TECH-LAPTOP-002"]
    rejected_codes = {
        reason["code"]
        for result in rejected
        for reason in result["reasons"]
    }
    assert "ATTRIBUTE_MISMATCH" in rejected_codes


def test_new_category_runs_through_existing_buyer_agent(client):
    created = client.post(
        "/intents",
        json={
            "merchant_id": "MERCHANT-003",
            "product_category": "cameras",
            "max_budget": 70000,
            "brand": "Canon",
            "brand_preference": "EXACT",
        },
    )
    assert created.status_code == 201
    intent_id = created.json()["intent_id"]

    selected = client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "VISION-CAMERA-001"},
    )
    assert selected.status_code == 200

    evaluation = client.post(f"/intents/{intent_id}/buyer-agent/evaluate")
    assert evaluation.status_code == 200
    body = evaluation.json()
    assert body["final_decision"]["decision"] == "ALLOW"
    assert body["buyer_agent"]["proposed_purchase"]["product_id"] == (
        "VISION-CAMERA-001"
    )
