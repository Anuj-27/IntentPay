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


def test_forgot_password_returns_a_token_for_a_known_merchant(client, db_session):
    seed_credential(db_session)

    response = client.post("/merchant/password/forgot", json={"merchant_id": MERCHANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["reset_token"]
    assert body["expires_in_seconds"] == 900


def test_forgot_password_does_not_reveal_whether_a_merchant_exists(client):
    response = client.post(
        "/merchant/password/forgot", json={"merchant_id": "no-such-merchant"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reset_token"] is None


def test_reset_token_changes_the_password_and_old_password_stops_working(client, db_session):
    seed_credential(db_session)

    forgot_response = client.post(
        "/merchant/password/forgot", json={"merchant_id": MERCHANT_ID}
    )
    token = forgot_response.json()["reset_token"]

    reset_response = client.post(
        "/merchant/password/reset",
        json={"reset_token": token, "new_password": "a-brand-new-password"},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["reset"] is True

    old_login = login(client, password=PASSWORD)
    assert old_login.status_code == 401

    new_login = login(client, password="a-brand-new-password")
    assert new_login.status_code == 200


def test_reset_token_can_only_be_used_once(client, db_session):
    seed_credential(db_session)
    token = client.post(
        "/merchant/password/forgot", json={"merchant_id": MERCHANT_ID}
    ).json()["reset_token"]

    first = client.post(
        "/merchant/password/reset",
        json={"reset_token": token, "new_password": "first-new-password"},
    )
    assert first.status_code == 200

    second = client.post(
        "/merchant/password/reset",
        json={"reset_token": token, "new_password": "second-new-password"},
    )
    assert second.status_code == 422
    assert second.json()["detail"]["reason_code"] == "RESET_TOKEN_INVALID"


def test_invalid_reset_token_is_rejected(client):
    response = client.post(
        "/merchant/password/reset",
        json={"reset_token": "not-a-real-token", "new_password": "whatever-password"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == "RESET_TOKEN_INVALID"


def test_reset_password_rejects_a_short_new_password(client, db_session):
    seed_credential(db_session)
    token = client.post(
        "/merchant/password/forgot", json={"merchant_id": MERCHANT_ID}
    ).json()["reset_token"]

    response = client.post(
        "/merchant/password/reset",
        json={"reset_token": token, "new_password": "short"},
    )
    assert response.status_code == 422
