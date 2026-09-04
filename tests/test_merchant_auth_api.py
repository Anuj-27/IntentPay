from backend.app.db.models import MerchantCredentialDB
from backend.app.services.security_service import hash_password


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


def test_login_fails_with_no_seeded_credential(client):
    response = login(client)
    assert response.status_code == 401
    assert response.json()["detail"]["reason_code"] == "MERCHANT_CREDENTIALS_INVALID"


def test_login_fails_with_wrong_password(client, db_session):
    seed_credential(db_session)
    response = login(client, password="wrong-password")
    assert response.status_code == 401


def test_login_succeeds_and_sets_session(client, db_session):
    seed_credential(db_session)
    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == MERCHANT_ID
    assert body["display_name"] == "DemoStore"

    session_response = client.get("/merchant/session")
    assert session_response.status_code == 200
    assert session_response.json()["merchant_id"] == MERCHANT_ID


def test_session_requires_login(client):
    response = client.get("/merchant/session")
    assert response.status_code == 401
    assert response.json()["detail"]["reason_code"] == "MERCHANT_SESSION_REQUIRED"


def test_logout_clears_session(client, db_session):
    seed_credential(db_session)
    login(client)
    assert client.get("/merchant/session").status_code == 200

    logout_response = client.post("/merchant/session/logout")
    assert logout_response.status_code == 200
    assert client.get("/merchant/session").status_code == 401


def test_catalog_requires_login(client):
    response = client.get("/merchant/catalog")
    assert response.status_code == 401


def test_dashboard_catalog_lists_static_products(client, db_session):
    seed_credential(db_session)
    login(client)

    response = client.get("/merchant/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == MERCHANT_ID
    product_ids = {entry["product"]["product_id"] for entry in body["products"]}
    assert "PROD-001" in product_ids
    entry = next(e for e in body["products"] if e["product"]["product_id"] == "PROD-001")
    assert entry["is_custom"] is False
    assert entry["is_active"] is True


def new_product_payload(product_id="PROD-NEW-1"):
    return {
        "product_id": product_id,
        "name": "Test Wireless Buds",
        "category": "headphones",
        "price": 2999,
        "brand": "Sony",
        "color": "white",
        "rating": 4.1,
        "features": ["lightweight"],
        "in_stock": True,
    }


def test_creating_a_product_makes_it_appear_in_the_live_buyer_catalog(client, db_session):
    seed_credential(db_session)
    login(client)

    create_response = client.post(
        "/merchant/catalog/products", json=new_product_payload()
    )
    assert create_response.status_code == 201
    assert create_response.json()["is_custom"] is True

    buyer_response = client.get(f"/products?merchant_id={MERCHANT_ID}")
    assert buyer_response.status_code == 200
    buyer_ids = {p["product_id"] for p in buyer_response.json()["products"]}
    assert "PROD-NEW-1" in buyer_ids


def test_editing_a_static_product_changes_the_live_price(client, db_session):
    seed_credential(db_session)
    login(client)

    payload = {
        "product_id": "PROD-001",
        "name": "Sony Basic Wireless",
        "category": "headphones",
        "price": 2599,
        "brand": "Sony",
        "color": "black",
        "rating": 4.2,
        "features": ["30-hour battery", "basic microphone"],
        "in_stock": True,
    }
    update_response = client.put(
        "/merchant/catalog/products/PROD-001", json=payload
    )
    assert update_response.status_code == 200
    assert update_response.json()["is_custom"] is False

    buyer_response = client.get(f"/products?merchant_id={MERCHANT_ID}")
    edited = next(
        p for p in buyer_response.json()["products"] if p["product_id"] == "PROD-001"
    )
    assert edited["price"] == 2599


def test_update_rejects_mismatched_product_id(client, db_session):
    seed_credential(db_session)
    login(client)

    response = client.put(
        "/merchant/catalog/products/PROD-001",
        json=new_product_payload(product_id="PROD-002"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == "PRODUCT_ID_MISMATCH"


def test_deactivating_a_product_hides_it_from_buyers_but_not_the_dashboard(
    client, db_session
):
    seed_credential(db_session)
    login(client)

    deactivate_response = client.post(
        "/merchant/catalog/products/PROD-001/deactivate"
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False

    buyer_response = client.get(f"/products?merchant_id={MERCHANT_ID}")
    buyer_ids = {p["product_id"] for p in buyer_response.json()["products"]}
    assert "PROD-001" not in buyer_ids

    dashboard_response = client.get("/merchant/catalog")
    entry = next(
        e
        for e in dashboard_response.json()["products"]
        if e["product"]["product_id"] == "PROD-001"
    )
    assert entry["is_active"] is False

    reactivate_response = client.post(
        "/merchant/catalog/products/PROD-001/activate"
    )
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["is_active"] is True

    buyer_response_after = client.get(f"/products?merchant_id={MERCHANT_ID}")
    buyer_ids_after = {
        p["product_id"] for p in buyer_response_after.json()["products"]
    }
    assert "PROD-001" in buyer_ids_after


def test_deactivating_unknown_product_returns_404(client, db_session):
    seed_credential(db_session)
    login(client)

    response = client.post("/merchant/catalog/products/DOES-NOT-EXIST/deactivate")
    assert response.status_code == 404
    assert response.json()["detail"]["reason_code"] == "PRODUCT_NOT_FOUND"


def test_register_creates_a_working_session_and_dashboard(client):
    response = client.post(
        "/merchant/register",
        json={
            "merchant_id": "new-merchant-1",
            "display_name": "Brand New Store",
            "password": "a-strong-password",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["merchant_id"] == "new-merchant-1"
    assert body["display_name"] == "Brand New Store"

    session_response = client.get("/merchant/session")
    assert session_response.status_code == 200
    assert session_response.json()["merchant_id"] == "new-merchant-1"

    dashboard_response = client.get("/merchant/catalog")
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["count"] == 0


def test_register_rejects_a_merchant_id_already_used_by_a_static_demo_merchant(client):
    response = client.post(
        "/merchant/register",
        json={
            "merchant_id": MERCHANT_ID,
            "display_name": "Impersonator",
            "password": "a-strong-password",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "MERCHANT_ID_TAKEN"


def test_register_rejects_a_merchant_id_already_self_registered(client):
    payload = {
        "merchant_id": "duplicate-store",
        "display_name": "First",
        "password": "a-strong-password",
    }
    assert client.post("/merchant/register", json=payload).status_code == 201

    second = dict(payload, display_name="Second")
    response = client.post("/merchant/register", json=second)
    assert response.status_code == 409


def test_register_rejects_a_short_password(client):
    response = client.post(
        "/merchant/register",
        json={
            "merchant_id": "short-pw-store",
            "display_name": "Store",
            "password": "short",
        },
    )
    assert response.status_code == 422


def test_register_rejects_an_invalid_merchant_id(client):
    response = client.post(
        "/merchant/register",
        json={
            "merchant_id": "a b!",
            "display_name": "Store",
            "password": "a-strong-password",
        },
    )
    assert response.status_code == 422


def test_a_newly_registered_merchant_can_sell_and_is_discoverable(client):
    client.post(
        "/merchant/register",
        json={
            "merchant_id": "fresh-audio-store",
            "display_name": "Fresh Audio",
            "password": "a-strong-password",
        },
    )
    create_response = client.post(
        "/merchant/catalog/products",
        json=new_product_payload(product_id="FRESH-001"),
    )
    assert create_response.status_code == 201

    buyer_response = client.get("/products?merchant_id=fresh-audio-store")
    assert buyer_response.status_code == 200
    product_ids = {p["product_id"] for p in buyer_response.json()["products"]}
    assert "FRESH-001" in product_ids

    merchants_response = client.get("/merchants")
    merchant_ids = {m["merchant_id"] for m in merchants_response.json()["merchants"]}
    assert "fresh-audio-store" in merchant_ids

    categories_response = client.get("/categories")
    headphones = next(
        c for c in categories_response.json()["categories"] if c["category_id"] == "headphones"
    )
    assert "fresh-audio-store" in headphones["merchant_ids"]


def test_is_custom_survives_a_second_dashboard_read(client, db_session):
    """Regression test: get_merchant_or_404(..., db=db) merges the buyer-
    facing overlay by default, which previously leaked into the dashboard's
    own is_custom/is_active bookkeeping -- a product added by the merchant
    looked non-custom as soon as you re-fetched the dashboard after the
    initial create response."""
    seed_credential(db_session)
    login(client)
    client.post("/merchant/catalog/products", json=new_product_payload(product_id="PROD-NEW-1"))

    first_read = client.get("/merchant/catalog").json()
    second_read = client.get("/merchant/catalog").json()
    for payload in (first_read, second_read):
        entry = next(e for e in payload["products"] if e["product"]["product_id"] == "PROD-NEW-1")
        assert entry["is_custom"] is True
        assert entry["is_active"] is True

    static_entry = next(e for e in second_read["products"] if e["product"]["product_id"] == "PROD-001")
    assert static_entry["is_custom"] is False


def test_writes_are_isolated_to_the_authenticated_merchant(client, db_session):
    seed_credential(db_session, merchant_id="MERCHANT-002", password="tech-password")
    login_response = login(client, merchant_id="MERCHANT-002", password="tech-password")
    assert login_response.status_code == 200

    create_response = client.post(
        "/merchant/catalog/products",
        json=new_product_payload(product_id="TECH-NEW-1"),
    )
    assert create_response.status_code == 201

    other_merchant_products = client.get(f"/products?merchant_id={MERCHANT_ID}")
    other_ids = {p["product_id"] for p in other_merchant_products.json()["products"]}
    assert "TECH-NEW-1" not in other_ids
