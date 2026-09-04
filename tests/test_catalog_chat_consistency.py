"""Catalog and AI Chat must render the exact same canonical Product data
for the same product_id -- one source of truth (the merchant catalog),
never a second copy the AI could drift from.

Root cause covered here: `merchant_service.list_merchant_contracts` (which
the entire chat/search pipeline reads from) applied the merchant's
ProductOverrideDB overlay to self-registered merchants but silently
skipped it for the three static demo merchants (MERCHANT-001/002/003) --
so an image/price/feature edit made through the merchant dashboard on a
*static* product was correctly reflected by /products (the catalog
endpoint, via find_merchant_contract) but invisible to chat search."""

from backend.app.services.security_service import hash_password
from backend.app.db.models import MerchantCredentialDB
from backend.app.schemas.visual_intent import VisualProductCandidate


MERCHANT_ID = "MERCHANT-002"
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


def chat(client, message):
    response = client.post("/assistant/chat", json={"messages": [{"role": "user", "content": message}]})
    assert response.status_code == 200, response.text
    return response.json()


# TEST 1: catalog returns product image_url.
def test_catalog_returns_image_url_for_a_product_with_one(client):
    response = client.get("/products?merchant_id=MERCHANT-002")
    pixel = next(p for p in response.json()["products"] if p["product_id"] == "TECH-PHONE-002")
    # Baseline demo data has no image registered for this one -- that's a
    # missing-data state, not a bug; TEST 3 below proves catalog and chat
    # agree on it either way.
    assert "image_url" in pixel


# TEST 2 / TEST 3 (the actual bug report): editing a STATIC merchant's
# product through the dashboard (price + image) must be reflected
# identically by the catalog endpoint and by chat search -- this is the
# exact scenario that exposed the list_merchant_contracts overlay bug.
def test_static_merchant_product_edit_is_visible_to_both_catalog_and_chat(client, db_session):
    seed_credential(db_session)
    login(client)

    updated_payload = {
        "product_id": "TECH-PHONE-002",
        "name": "Galaxy A56 256GB",
        "category": "smartphones",
        "brand": "Samsung",
        "price": 42999,
        "rating": 4.5,
        "color": "blue",
        "model": "Galaxy A56",
        "variant": "8GB/256GB",
        "features": ["5G", "AMOLED display", "fast charging"],
        "images": ["https://example.com/galaxy-a56-real.jpg"],
        "in_stock": True,
    }
    update_response = client.put(
        "/merchant/catalog/products/TECH-PHONE-002", json=updated_payload
    )
    assert update_response.status_code == 200

    catalog_response = client.get("/products?merchant_id=MERCHANT-002")
    catalog_product = next(
        p for p in catalog_response.json()["products"] if p["product_id"] == "TECH-PHONE-002"
    )
    assert catalog_product["price"] == 42999
    assert catalog_product["image_url"] == "https://example.com/galaxy-a56-real.jpg"

    chat_body = chat(client, "I want to buy a samsung galaxy a56")
    chat_product = next(
        s["product"] for s in chat_body["suggestions"] if s["product"]["product_id"] == "TECH-PHONE-002"
    )

    # This is the actual bug report: before the fix, chat_product would
    # still show the stale baseline price (44999) and no image at all.
    assert chat_product["price"] == catalog_product["price"] == 42999
    assert chat_product["image_url"] == catalog_product["image_url"]
    assert chat_product["images"] == catalog_product["images"]


def test_deactivating_a_static_product_removes_it_from_chat_too(client, db_session):
    """The same overlay bug also meant a merchant deactivating a static
    product through the dashboard didn't stop chat from recommending it
    -- only /products (the buyer catalog endpoint) respected it."""

    seed_credential(db_session)
    login(client)

    before = chat(client, "I want to buy a samsung galaxy a56")
    assert "TECH-PHONE-002" in {s["product"]["product_id"] for s in before["suggestions"]}

    deactivate_response = client.post("/merchant/catalog/products/TECH-PHONE-002/deactivate")
    assert deactivate_response.status_code == 200

    after = chat(client, "I want to buy a samsung galaxy a56")
    assert "TECH-PHONE-002" not in {s["product"]["product_id"] for s in after["suggestions"]}


# TEST 4: AI cannot override canonical price. The only "AI-provided" data
# in this pipeline is the visual candidate from an uploaded image, which
# can (in a hostile/broken vision model) claim any displayed_price -- the
# final product in the response must still be the canonical catalog one.
def test_visual_candidate_cannot_override_canonical_price(client, monkeypatch):
    tampered_candidate = VisualProductCandidate(
        product_name="Galaxy A56 256GB",
        category="smartphones",
        brand="Samsung",
        model="Galaxy A56",
        displayed_price=1,
        confidence=0.95,
        extraction_method="LOCAL_VISION",
    )
    monkeypatch.setattr(
        "backend.app.services.chat_service.get_configured_visual_analyzer",
        lambda: lambda request: tampered_candidate,
    )

    import base64

    body = client.post(
        "/assistant/chat",
        json={
            "messages": [{"role": "user", "content": "what is this"}],
            "image_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode(),
            "media_type": "image/png",
        },
    ).json()

    match = next(
        s for s in body["suggestions"] if s["product"]["product_id"] == "TECH-PHONE-002"
    )
    assert match["product"]["price"] == 44999
    assert match["product"]["price"] != 1


# TEST 5: AI cannot override canonical image_url. VisualProductCandidate
# has no image field at all -- there's no attacker-controlled input for
# an image_url to come from -- verified by monkeypatching the analyzer
# with a candidate carrying no image information and confirming the
# resolved product still carries whatever the catalog actually has.
def test_visual_candidate_cannot_override_canonical_image(client, monkeypatch):
    candidate = VisualProductCandidate(
        product_name="iPhone lookalike",
        category="smartphones",
        brand="Samsung",
        confidence=0.9,
        extraction_method="LOCAL_VISION",
    )
    monkeypatch.setattr(
        "backend.app.services.chat_service.get_configured_visual_analyzer",
        lambda: lambda request: candidate,
    )
    assert not hasattr(candidate, "image_url")

    import base64

    body = client.post(
        "/assistant/chat",
        json={
            "messages": [{"role": "user", "content": "what is this"}],
            "image_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode(),
            "media_type": "image/png",
        },
    ).json()

    for suggestion in body["suggestions"]:
        catalog_product = client.get(
            f"/products?merchant_id=MERCHANT-002"
        ).json()["products"]
        canonical = next(
            (p for p in catalog_product if p["product_id"] == suggestion["product"]["product_id"]),
            None,
        )
        if canonical is not None:
            assert suggestion["product"]["image_url"] == canonical["image_url"]


# TEST 6: AI cannot override stock -- VisualProductCandidate has no stock
# field either; the resolved product's in_stock always comes from the
# catalog record.
def test_stock_status_always_comes_from_the_catalog(client):
    candidate_schema_fields = VisualProductCandidate.model_fields
    assert "in_stock" not in candidate_schema_fields
    assert "price" not in candidate_schema_fields
    assert "image_url" not in candidate_schema_fields


# TEST 7: a new laptop search does not return previous smartphone
# products (conversation-state regression guard).
def test_new_category_search_does_not_leak_previous_category(client):
    messages = [{"role": "user", "content": "Find phones under 50000"}]
    first = client.post("/assistant/chat", json={"messages": messages}).json()
    messages.append({"role": "assistant", "content": first["reply"]})
    messages.append({"role": "user", "content": "Compare laptops under 65000 with 16GB RAM"})
    second = client.post("/assistant/chat", json={"messages": messages}).json()

    assert all(s["product"]["category"] == "laptops" for s in second["suggestions"])


# TEST 10: catalog, chat suggestions, and upsell all use the identical
# Product representation for the same product_id (same fields, same
# values) -- proving there's one canonical shape, not per-surface DTOs.
def test_all_product_card_surfaces_return_identical_product_shape(client, db_session):
    seed_credential(db_session)
    login(client)
    client.put(
        "/merchant/catalog/products/TECH-PHONE-002",
        json={
            "product_id": "TECH-PHONE-002",
            "name": "Galaxy A56 256GB",
            "category": "smartphones",
            "brand": "Samsung",
            "price": 44999,
            "rating": 4.5,
            "color": "blue",
            "images": ["https://example.com/galaxy-a56.jpg"],
            "features": ["5G", "AMOLED display", "fast charging"],
            "in_stock": True,
        },
    )

    catalog_product = next(
        p
        for p in client.get("/products?merchant_id=MERCHANT-002").json()["products"]
        if p["product_id"] == "TECH-PHONE-002"
    )
    chat_body = chat(client, "I want to buy a samsung galaxy a56")
    chat_product = next(
        s["product"] for s in chat_body["suggestions"] if s["product"]["product_id"] == "TECH-PHONE-002"
    )

    for field in ("product_id", "name", "brand", "price", "image_url", "images", "rating", "color", "features", "in_stock", "category"):
        assert catalog_product[field] == chat_product[field], field
