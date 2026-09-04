def test_cross_origin_merchant_mutation_is_rejected(client):
    response = client.post(
        "/merchant/catalog/products",
        headers={"Origin": "https://attacker.example"},
        json={},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason_code"] == "CROSS_ORIGIN_MUTATION"


def test_same_origin_merchant_mutation_reaches_authentication(client):
    response = client.post(
        "/merchant/catalog/products",
        headers={"Origin": "http://testserver"},
        json={},
    )

    # Origin validation passed; the normal endpoint authentication then
    # rejected the request because this client is not logged in.
    assert response.status_code == 401


def test_secure_mode_requires_origin_or_referer_for_merchant_mutations(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MERCHANT_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("APP_ORIGIN", "https://intentpay.example")

    response = client.post(
        "/merchant/catalog/products",
        json={},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason_code"] == "ORIGIN_REQUIRED"
