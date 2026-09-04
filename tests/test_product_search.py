"""Covers the typo-tolerant product discovery pipeline end-to-end: a
merchant adds a product through the dashboard API, and a shopper finds it
through /assistant/chat even with misspelled, split, or partial queries --
with no server restart or cache warm-up in between. Mirrors the manual
test plan from the IntentPay search-and-images upgrade."""

from backend.app.services.security_service import hash_password
from backend.app.db.models import MerchantCredentialDB


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


def add_iphone(client):
    """Registers a fresh merchant and lists an iPhone 15 through the same
    dashboard API a real merchant would use -- nothing about "iPhone" is
    seeded anywhere in the static demo catalog."""

    client.post(
        "/merchant/register",
        json={
            "merchant_id": "apple-store",
            "display_name": "Apple Store",
            "password": "a-strong-password",
        },
    )
    response = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "PROD-IP15-001",
            "name": "Apple iPhone 15",
            "category": "smartphones",
            "brand": "Apple",
            "price": 69900,
            "rating": 4.7,
            "color": "Black",
            "model": "iPhone 15",
            "features": ["A16 Bionic chip", "48MP camera", "USB-C", "5G"],
            "images": [
                "https://example.com/iphone15-front.jpg",
                "https://example.com/iphone15-back.jpg",
            ],
            "in_stock": True,
        },
    )
    assert response.status_code == 201
    return response


def chat(client, message, **updates):
    body = {"messages": [{"role": "user", "content": message}]}
    body.update(updates)
    return client.post("/assistant/chat", json=body)


def test_newly_added_product_is_immediately_searchable_without_restart(client):
    add_iphone(client)

    response = chat(client, "I want to buy iphone")
    body = response.json()

    assert response.status_code == 200
    product_ids = {s["product"]["product_id"] for s in body["suggestions"]}
    assert "PROD-IP15-001" in product_ids


def test_typo_and_split_word_variants_all_find_the_iphone(client):
    add_iphone(client)

    typo_queries = [
        "I want to by iphone",
        "I want to bui iphone",
        "i want to buy ipone",
        "i want iphone",
        "i want to by an iphon",
        "show me an iphne",
        "i want to purchse iphone",
        "show me iphones",
        "i want to buy i phone",
    ]

    for query in typo_queries:
        response = chat(client, query)
        assert response.status_code == 200, query
        body = response.json()
        product_ids = {s["product"]["product_id"] for s in body["suggestions"]}
        assert "PROD-IP15-001" in product_ids, f"{query!r} did not surface the iPhone: {body}"
        assert body["suggestions"][0]["product"]["product_id"] == "PROD-IP15-001", query


def test_generic_typo_tolerance_is_not_iphone_specific(client):
    """The same fuzzy pipeline must work for any brand/category typo, not
    just "iphone" -- proves the search isn't a hard-coded special case."""

    samsung_response = chat(client, "show me samzung phones")
    assert samsung_response.status_code == 200
    samsung_body = samsung_response.json()
    assert samsung_body["intent"]["category"] == "smartphones"
    assert any(
        s["product"]["brand"] == "Samsung" for s in samsung_body["suggestions"]
    )
    assert samsung_body["suggestions"][0]["product"]["brand"] == "Samsung"

    laptop_response = chat(client, "lapotp under 70000")
    assert laptop_response.status_code == 200
    laptop_body = laptop_response.json()
    assert laptop_body["intent"]["category"] == "laptops"
    assert laptop_body["suggestions"]

    headphones_response = chat(client, "sony hedphones")
    assert headphones_response.status_code == 200
    headphones_body = headphones_response.json()
    assert headphones_body["intent"]["category"] == "headphones"
    assert headphones_body["suggestions"][0]["product"]["brand"] == "Sony"


def test_deactivating_a_product_removes_it_from_chat_search(client, db_session):
    seed_credential(db_session)
    login(client)
    add_iphone(client)

    before = chat(client, "I want to buy iphone").json()
    assert "PROD-IP15-001" in {s["product"]["product_id"] for s in before["suggestions"]}

    deactivate = client.post("/merchant/catalog/products/PROD-IP15-001/deactivate")
    assert deactivate.status_code == 200

    after = chat(client, "I want to buy iphone").json()
    assert "PROD-IP15-001" not in {s["product"]["product_id"] for s in after["suggestions"]}


def test_budget_ceiling_is_never_overridden_by_fuzzy_similarity(client):
    """A strong user constraint (an explicit budget) must win over a
    higher-scoring but over-budget fuzzy match -- the over-budget option
    can only appear in the separate upsell list, never as a primary
    suggestion."""

    add_iphone(client)
    client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "PROD-IP15PRO-001",
            "name": "Apple iPhone 15 Pro",
            "category": "smartphones",
            "brand": "Apple",
            "price": 129900,
            "rating": 4.9,
            "color": "Titanium",
            "model": "iPhone 15 Pro",
            "features": ["A17 Pro chip", "48MP camera", "titanium", "USB-C", "5G"],
            "in_stock": True,
        },
    )

    response = chat(client, "I want an Apple iPhone under 70000")
    body = response.json()

    assert response.status_code == 200
    assert body["suggestions"], body
    assert body["suggestions"][0]["product"]["product_id"] == "PROD-IP15-001"
    assert all(s["total_amount"] <= 70000 for s in body["suggestions"])
    assert all(
        s["product"]["product_id"] != "PROD-IP15PRO-001" for s in body["suggestions"]
    )


def test_mobile_budget_boundary_separates_approved_and_reauthorization_options(client):
    add_iphone(client)
    above_budget = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "PROD-PHONE-73000",
            "name": "Premium Phone 73000",
            "category": "smartphones",
            "price": 73000,
            "brand": "Example",
            "rating": 4.9,
            "features": ["premium camera", "wireless charging", "5G"],
            "in_stock": True,
        },
    )
    assert above_budget.status_code == 201

    response = chat(client, "best mobile under ₹69900")
    body = response.json()

    assert response.status_code == 200
    assert body["intent"]["max_budget"] == 69900
    assert body["suggestions"]
    assert all(
        suggestion["total_amount"] <= 69900
        and suggestion["product"]["product_id"] != "PROD-PHONE-73000"
        for suggestion in body["suggestions"]
    )

    upsell = next(
        candidate
        for candidate in body["upsell_candidates"]
        if candidate["product"]["product_id"] == "PROD-PHONE-73000"
    )
    assert upsell["total_amount"] == 73000
    assert upsell["status"] == "REQUIRES_REAUTHORIZATION"


def test_multi_image_round_trip_and_primary_selection(client):
    create_response = add_iphone(client)
    created_images = create_response.json()["product"]["images"]
    assert created_images == [
        {"url": "https://example.com/iphone15-front.jpg", "is_primary": True},
        {"url": "https://example.com/iphone15-back.jpg", "is_primary": False},
    ]

    buyer_response = client.get("/products?merchant_id=apple-store")
    product = next(
        p for p in buyer_response.json()["products"] if p["product_id"] == "PROD-IP15-001"
    )
    assert len(product["images"]) == 2
    assert product["image_url"] == "https://example.com/iphone15-front.jpg"

    chat_body = chat(client, "I want to buy iphone").json()
    suggestion = next(
        s for s in chat_body["suggestions"] if s["product"]["product_id"] == "PROD-IP15-001"
    )
    assert suggestion["product"]["images"][0]["url"] == "https://example.com/iphone15-front.jpg"


def test_legacy_single_image_url_still_works(client):
    client.post(
        "/merchant/register",
        json={"merchant_id": "legacy-store", "display_name": "Legacy Store", "password": "a-strong-password"},
    )
    response = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "LEGACY-001",
            "name": "Legacy Headphones",
            "category": "headphones",
            "brand": "Sony",
            "price": 2999,
            "rating": 4.0,
            "image_url": "https://example.com/legacy.jpg",
            "in_stock": True,
        },
    )
    assert response.status_code == 201
    body = response.json()["product"]
    assert body["image_url"] == "https://example.com/legacy.jpg"
    assert body["images"] == [{"url": "https://example.com/legacy.jpg", "is_primary": True}]


def test_product_image_url_must_be_http_or_https(client):
    client.post(
        "/merchant/register",
        json={"merchant_id": "bad-image-store", "display_name": "Store", "password": "a-strong-password"},
    )
    response = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "BAD-IMG-001",
            "name": "Broken Image Product",
            "category": "headphones",
            "brand": "Sony",
            "price": 1999,
            "rating": 4.0,
            "images": ["javascript:alert(1)"],
            "in_stock": True,
        },
    )
    assert response.status_code == 422


def test_locally_uploaded_image_is_accepted_as_a_base64_data_url(client):
    """Mirrors what the merchant dashboard's "Upload from device" button
    sends: a base64 data URL instead of a hosted image URL, since this
    project has no separate file-storage service to upload to."""

    client.post(
        "/merchant/register",
        json={"merchant_id": "upload-store", "display_name": "Store", "password": "a-strong-password"},
    )
    tiny_png_base64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42"
        "YAAAAASUVORK5CYII="
    )
    data_url = f"data:image/png;base64,{tiny_png_base64}"

    response = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "UPLOAD-001",
            "name": "Uploaded Photo Product",
            "category": "headphones",
            "brand": "Sony",
            "price": 1999,
            "rating": 4.0,
            "images": [data_url],
            "in_stock": True,
        },
    )

    assert response.status_code == 201
    product = response.json()["product"]
    assert product["images"] == [{"url": data_url, "is_primary": True}]
    assert product["image_url"] == data_url

    buyer_response = client.get("/products?merchant_id=upload-store")
    fetched = next(
        p for p in buyer_response.json()["products"] if p["product_id"] == "UPLOAD-001"
    )
    assert fetched["images"][0]["url"] == data_url


def test_malformed_data_url_is_rejected(client):
    client.post(
        "/merchant/register",
        json={"merchant_id": "bad-upload-store", "display_name": "Store", "password": "a-strong-password"},
    )
    response = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "BAD-UPLOAD-001",
            "name": "Bad Upload Product",
            "category": "headphones",
            "brand": "Sony",
            "price": 1999,
            "rating": 4.0,
            "images": ["data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="],
            "in_stock": True,
        },
    )
    assert response.status_code == 422


def test_empty_and_duplicate_image_urls_are_ignored(client):
    client.post(
        "/merchant/register",
        json={"merchant_id": "dedupe-store", "display_name": "Store", "password": "a-strong-password"},
    )
    response = client.post(
        "/merchant/catalog/products",
        json={
            "product_id": "DEDUPE-001",
            "name": "Deduped Image Product",
            "category": "headphones",
            "brand": "Sony",
            "price": 1999,
            "rating": 4.0,
            "images": [
                "",
                "https://example.com/a.png",
                "https://example.com/a.png",
                "  ",
            ],
            "in_stock": True,
        },
    )
    assert response.status_code == 201
    images = response.json()["product"]["images"]
    assert images == [{"url": "https://example.com/a.png", "is_primary": True}]
