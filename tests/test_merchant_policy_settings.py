"""GET/PATCH /merchant/policy.

Regression coverage for a real bug found live: PATCH wrote
autonomous_transaction_limit straight to the database without checking it
against that merchant's own max_transaction_amount. MerchantPolicy's
Pydantic validator only catches the invalid combination when the row is
later *read* back (e.g. by /categories, which lists every merchant's
contract) -- so one bad PATCH silently poisoned every subsequent request
that touched the merchant list, for every merchant, not just the
misconfigured one.
"""

MERCHANT_ID = "policy-settings-test-merchant"
PASSWORD = "policy-settings-test-pw-1"


def register_and_login(client):
    response = client.post(
        "/merchant/register",
        json={
            "merchant_id": MERCHANT_ID,
            "display_name": "Policy Settings Test Store",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    return response


def test_get_policy_returns_defaults_after_registration(client):
    register_and_login(client)
    response = client.get("/merchant/policy")
    assert response.status_code == 200
    body = response.json()
    assert body["autonomous_transaction_limit"] == 50_000
    assert body["max_transaction_amount"] == 500_000


def test_patch_updates_autonomous_limit_within_the_hard_ceiling(client):
    register_and_login(client)
    response = client.patch(
        "/merchant/policy",
        json={"autonomous_transaction_limit": 100_000},
    )
    assert response.status_code == 200
    assert response.json()["autonomous_transaction_limit"] == 100_000

    # It actually persisted, and the merchant contract can still be built
    # (i.e. the previously-committed corruption bug is not present).
    refetched = client.get("/merchant/policy")
    assert refetched.json()["autonomous_transaction_limit"] == 100_000


def test_patch_rejects_a_limit_above_the_hard_ceiling(client):
    register_and_login(client)
    response = client.patch(
        "/merchant/policy",
        json={"autonomous_transaction_limit": 999_999_999},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == "AUTONOMOUS_LIMIT_EXCEEDS_HARD_CEILING"

    # The rejected value must not have been written -- confirmed two ways:
    # the policy read-back is unchanged, and /categories (which lists
    # every merchant's contract) still works for everyone.
    unchanged = client.get("/merchant/policy")
    assert unchanged.json()["autonomous_transaction_limit"] == 50_000

    categories_response = client.get("/categories")
    assert categories_response.status_code == 200


def test_demo_merchant_policy_is_not_editable(client):
    login = client.post(
        "/merchant/session/login",
        json={"merchant_id": "MERCHANT-001", "password": "IntentPayDemo!2026"},
    )
    if login.status_code != 200:
        # The seeded demo credential migration may not have run against
        # this test's database -- this test only asserts PATCH behavior,
        # so skip cleanly rather than failing on an unrelated setup gap.
        import pytest

        pytest.skip("MERCHANT-001 demo credential not seeded in this test database")

    response = client.patch(
        "/merchant/policy",
        json={"autonomous_transaction_limit": 4000},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "MERCHANT_POLICY_NOT_EDITABLE"
