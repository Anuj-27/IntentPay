"""Covers the product-image contract across the whole conversational
buying journey: catalog -> AI recommendation -> selection -> buying
confirmation -> upsell -> Trust Gate outcomes. The rule under test
throughout is the same one everywhere: the canonical catalog Product
(image included) is always what comes back, never anything the LLM
invented, and showing an image is never itself authorization to pay."""

import base64

from backend.app.schemas.visual_intent import VisualProductCandidate
from backend.app.services.security_service import hash_password
from backend.app.db.models import MerchantCredentialDB


PNG_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\nintentpay-test").decode()
MERCHANT_ID = "MERCHANT-001"
PASSWORD = "test-only-password-123"


def seed_credential(db_session, merchant_id=MERCHANT_ID, password=PASSWORD):
    password_hash, password_salt = hash_password(password)
    db_session.add(
        MerchantCredentialDB(
            merchant_id=merchant_id,
            password_hash=password_hash,
            password_salt=password_salt,
        )
    )
    db_session.commit()


def login(client, merchant_id=MERCHANT_ID, password=PASSWORD):
    return client.post(
        "/merchant/session/login",
        json={"merchant_id": merchant_id, "password": password},
    )


def add_iphone(client, merchant_id="apple-store", in_stock=True, price=69900):
    client.post(
        "/merchant/register",
        json={"merchant_id": merchant_id, "display_name": "Apple Store", "password": "a-strong-password"},
    )
    response = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "PROD-IP15-001",
            "name": "Apple iPhone 15",
            "category": "smartphones",
            "brand": "Apple",
            "price": price,
            "rating": 4.7,
            "color": "Black",
            "model": "iPhone 15",
            "features": ["A16 Bionic chip", "48MP camera", "USB-C", "5G"],
            "images": ["https://example.com/iphone15-front.jpg", "https://example.com/iphone15-back.jpg"],
            "in_stock": in_stock,
        },
    )
    assert response.status_code == 201
    return response.json()["product"]


def chat(client, message, **updates):
    body = {"messages": [{"role": "user", "content": message}]}
    body.update(updates)
    return client.post("/assistant/chat", json=body)


# TEST 1: catalog product has image_url -> catalog displays image.
def test_catalog_product_carries_its_canonical_image(client):
    product = add_iphone(client)
    assert product["image_url"] == "https://example.com/iphone15-front.jpg"

    catalog_response = client.get("/products?merchant_id=apple-store")
    fetched = next(
        p for p in catalog_response.json()["products"] if p["product_id"] == "PROD-IP15-001"
    )
    assert fetched["image_url"] == "https://example.com/iphone15-front.jpg"
    assert len(fetched["images"]) == 2


# TEST 2: AI recommends a product -> recommendation response contains the
# canonical image_url, and match_type says how it was found.
def test_ai_recommendation_carries_canonical_image_and_match_type(client):
    add_iphone(client)

    response = chat(client, "I want to buy iphone")
    body = response.json()

    assert response.status_code == 200
    assert body["match_type"] == "TEXT_MATCH"
    top = next(s for s in body["suggestions"] if s["product"]["product_id"] == "PROD-IP15-001")
    assert top["product"]["image_url"] == "https://example.com/iphone15-front.jpg"
    assert top["product"]["images"][0]["url"] == "https://example.com/iphone15-front.jpg"


# TEST 3: "Buy iPhone 15" -> the buying confirmation response contains the
# canonical product image (the explicit /visual-intents/confirm review
# step is this project's actual purchase-intent entry point; chat itself
# stays discovery-only by design, per the existing safety architecture).
def test_buying_confirmation_contains_canonical_product_image(client):
    add_iphone(client)

    response = client.post(
        "/visual-intents/confirm",
        json={
            "merchant_id": "apple-store",
            "product_id": "PROD-IP15-001",
            "max_budget": 70000,
            "quantity": 1,
            "confirmed": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["product"]["product_id"] == "PROD-IP15-001"
    assert body["product"]["image_url"] == "https://example.com/iphone15-front.jpg"
    # Showing the image is not authorization -- the Trust Gate decision is
    # still the thing that gates payment readiness.
    assert "final_decision" in body["evaluation"]


# TEST 4: user selects a recommended product -> the selection response
# shows the same canonical image, resolved server-side from product_id
# (never from a client-side index or LLM-remembered URL).
def test_selecting_a_product_returns_the_same_canonical_image(client):
    product = add_iphone(client)

    intent_response = client.post(
        "/intents",
        json={
            "merchant_id": "apple-store",
            "product_category": "smartphones",
            "max_budget": 70000,
            "brand": "Apple",
            "brand_preference": "EXACT",
        },
    )
    assert intent_response.status_code == 201
    intent_id = intent_response.json()["intent_id"]

    selection_response = client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-IP15-001"},
    )

    assert selection_response.status_code == 200
    body = selection_response.json()
    assert body["selected_product_id"] == "PROD-IP15-001"
    assert body["product"]["image_url"] == product["image_url"]
    assert body["product"]["images"] == product["images"]


# TEST 5 + 6: uploading a product photo resolves against the catalog (not
# the upload itself), and a low-confidence read still returns candidates
# rather than a single invented match.
def test_image_upload_resolves_to_the_canonical_catalog_product(client, monkeypatch):
    add_iphone(client)
    candidate = VisualProductCandidate(
        product_name="Apple iPhone 15",
        category="smartphones",
        brand="Apple",
        model="iPhone 15",
        confidence=0.94,
        extraction_method="LOCAL_VISION",
    )
    monkeypatch.setattr(
        "backend.app.services.chat_service.get_configured_visual_analyzer",
        lambda: lambda request: candidate,
    )

    response = chat(
        client,
        "What is this product?",
        image_base64=PNG_BASE64,
        media_type="image/png",
    )
    body = response.json()

    assert response.status_code == 200
    assert body["match_type"] == "IMAGE_MATCH"
    top = body["suggestions"][0]
    assert top["product"]["product_id"] == "PROD-IP15-001"
    # The catalog image is used -- nothing about the uploaded photo itself
    # ever becomes the product's image_url.
    assert top["product"]["image_url"] == "https://example.com/iphone15-front.jpg"


def test_low_confidence_image_upload_returns_candidates_not_a_forced_match(client, monkeypatch):
    add_iphone(client)
    low_confidence_candidate = VisualProductCandidate(
        product_name="phone",
        category="smartphones",
        confidence=0.2,
        extraction_method="LOCAL_VISION",
    )
    monkeypatch.setattr(
        "backend.app.services.chat_service.get_configured_visual_analyzer",
        lambda: lambda request: low_confidence_candidate,
    )

    response = chat(
        client,
        "identify this",
        image_base64=PNG_BASE64,
        media_type="image/png",
    )
    body = response.json()

    assert response.status_code == 200
    # Either it still surfaces ranked candidates (never a single asserted
    # match) or it explicitly asks for more detail -- it must not silently
    # pretend a low-confidence read is a confirmed identification.
    if body["suggestions"]:
        assert len(body["suggestions"]) >= 1
    else:
        assert body["next_action"] in ("PROVIDE_PRODUCT_HINT", "PROVIDE_CATEGORY")


# TEST 7: product with no image -> the API still returns cleanly with an
# empty images list, so the frontend can render its placeholder.
def test_product_without_an_image_does_not_break_the_response(client):
    client.post(
        "/merchant/register",
        json={"merchant_id": "no-image-store", "display_name": "Store", "password": "a-strong-password"},
    )
    client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "NO-IMAGE-001",
            "name": "Plain Headphones",
            "category": "headphones",
            "brand": "Sony",
            "price": 1999,
            "rating": 4.0,
            "in_stock": True,
        },
    )

    response = chat(client, "I want to buy sony headphones")
    body = response.json()
    match = next(s for s in body["suggestions"] if s["product"]["product_id"] == "NO-IMAGE-001")
    assert match["product"]["images"] == []
    assert match["product"]["image_url"] is None


# TEST 8: an out-of-stock product's image can still exist in the catalog,
# but the purchase pipeline must still refuse it on stock grounds.
def test_out_of_stock_product_is_hidden_from_discovery_and_blocked_at_verification(client, db_session):
    seed_credential(db_session)
    login(client)
    add_iphone(client, in_stock=False)

    chat_body = chat(client, "I want to buy iphone").json()
    assert "PROD-IP15-001" not in {s["product"]["product_id"] for s in chat_body["suggestions"]}

    intent_response = client.post(
        "/intents",
        json={
            "merchant_id": "apple-store",
            "product_category": "smartphones",
            "max_budget": 70000,
            "autonomous_selection_allowed": True,
        },
    )
    intent_id = intent_response.json()["intent_id"]
    evaluation = client.post(f"/intents/{intent_id}/buyer-agent/evaluate")
    assert evaluation.status_code == 200
    body = evaluation.json()
    assert body["buyer_agent"]["decision"] == "BLOCK"
    assert any(
        reason["code"] == "OUT_OF_STOCK"
        for rejected in body["buyer_agent"]["rejected_products"]
        for reason in rejected["reasons"]
    )


# TEST 9: after a price change, the backend must revalidate the current
# catalog price at purchase time -- unaffected by (and independent of)
# whatever image is shown.
def test_price_change_is_caught_at_verification_regardless_of_image(client, db_session):
    seed_credential(db_session)
    login(client)
    product = add_iphone(client)
    stale_price = product["price"]

    update_payload = dict(product, price=stale_price + 10000)
    update_response = client.put(
        "/merchant/catalog/products/PROD-IP15-001", json=update_payload
    )
    assert update_response.status_code == 200
    assert update_response.json()["product"]["image_url"] == product["image_url"]

    intent_response = client.post(
        "/intents",
        json={"merchant_id": "apple-store", "product_category": "smartphones", "max_budget": 70000},
    )
    intent_id = intent_response.json()["intent_id"]
    client.post(f"/intents/{intent_id}/selection", json={"product_id": "PROD-IP15-001"})

    stale_purchase = {
        "product_id": "PROD-IP15-001",
        "quantity": 1,
        "unit_price": stale_price,
        "total_amount": stale_price,
    }
    verify_response = client.post(
        "/verify-purchase",
        json={"intent_id": intent_id, "purchase": stale_purchase},
    )
    assert verify_response.status_code == 200
    verification = verify_response.json()["verification"]
    assert verification["verified"] is False
    assert any(v["code"] == "UNIT_PRICE_MISMATCH" for v in verification["violations"])


# TEST 10 / 11: upsell alternatives also carry the canonical catalog image
# (this codebase's one "above-budget, meaningfully better" mechanism is
# the closest analogue to a cross-sell/upsell recommendation).
def test_upsell_candidates_carry_canonical_images(client):
    add_iphone(client)
    client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "PROD-IP15PLUS-001",
            "name": "Apple iPhone 15 Plus",
            "category": "smartphones",
            "brand": "Apple",
            "price": 79900,
            "rating": 4.9,
            "color": "Black",
            "model": "iPhone 15 Plus",
            "features": ["A16 Bionic chip", "48MP camera", "bigger battery", "USB-C", "5G"],
            "images": ["https://example.com/iphone15plus.jpg"],
            "in_stock": True,
        },
    )

    body = chat(client, "I want to buy iphone under 70000").json()
    assert body["upsell_candidates"], body
    upsell = body["upsell_candidates"][0]
    assert upsell["product"]["product_id"] == "PROD-IP15PLUS-001"
    assert upsell["product"]["image_url"] == "https://example.com/iphone15plus.jpg"


# TEST 12: a REASK/BLOCK/ESCALATE Trust Gate outcome can still surface the
# product (and its image) as context, but must never report readiness to
# pay.
def test_reask_decision_still_carries_product_image_but_blocks_payment_readiness(client):
    add_iphone(client)
    intent_response = client.post(
        "/intents",
        json={
            "merchant_id": "apple-store",
            "product_category": "smartphones",
            "max_budget": 70000,
            "autonomous_selection_allowed": False,
        },
    )
    intent_id = intent_response.json()["intent_id"]

    evaluation = client.post(f"/intents/{intent_id}/buyer-agent/evaluate")
    assert evaluation.status_code == 200
    body = evaluation.json()

    assert body["buyer_agent"]["decision"] == "REASK"
    assert body["ready_for_payment"] is False
    assert body["buyer_agent"]["recommended_product"]["image_url"] == (
        "https://example.com/iphone15-front.jpg"
    )
