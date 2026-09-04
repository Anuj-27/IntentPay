"""User authorization (IntentMandate.max_budget) and merchant policy
(MerchantPolicy.autonomous_transaction_limit) are two independent
boundaries. Neither can override the other:

  - The merchant cannot authorize spending on the customer's behalf --
    an amount the user never authorized always REASKs, regardless of how
    generous the merchant's autonomous limit is.
  - The user's authorization cannot force autonomous execution above what
    the merchant allows -- an authorized amount above the merchant's
    autonomous_transaction_limit always ESCALATEs (to a real human review
    queue, never a silent ALLOW), regardless of how much the user
    authorized.

These tests exercise that boundary directly via evaluate_intent_pipeline
with a synthetic single-product merchant contract, so the exact rupee
amounts from the spec (₹70k/73k/80k/50k/100k) are precise and don't
depend on the demo catalog's real prices.
"""

from backend.app.schemas.decision import DecisionType
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.merchant import (
    MerchantCapabilities,
    MerchantCatalog,
    MerchantContract,
    MerchantProfile,
)
from backend.app.schemas.merchant_policy import MerchantPolicy
from backend.app.schemas.product import Product
from backend.app.schemas.purchase import ProposedPurchase
from backend.app.services.decision_engine import make_decision
from backend.app.services.intent_verifier import verify_purchase
from backend.app.services.orchestration_service import evaluate_intent_pipeline


PRODUCT_PRICE = 73_000


def high_value_contract(*, autonomous_transaction_limit, max_transaction_amount=None):
    """A merchant with exactly one product, priced at ₹73,000, so the
    Buyer Agent has an unambiguous choice under autonomous_selection."""
    product = Product(
        product_id="HV-PROD-001",
        name="Premium Device",
        category="laptops",
        price=PRODUCT_PRICE,
        brand="Acme",
        rating=4.6,
        features=["premium build"],
        in_stock=True,
    )
    policy = MerchantPolicy(
        merchant_id="HV-MERCHANT",
        max_transaction_amount=max_transaction_amount or (autonomous_transaction_limit or PRODUCT_PRICE) + 500_000,
        autonomous_transaction_limit=autonomous_transaction_limit,
    )
    return MerchantContract(
        merchant=MerchantProfile(
            merchant_id="HV-MERCHANT",
            display_name="High Value Merchant",
            active=True,
            capabilities=MerchantCapabilities(
                catalog_search=True,
                inventory_check=True,
                checkout=True,
                refunds=True,
            ),
            policy=policy,
        ),
        catalog=MerchantCatalog(merchant_id="HV-MERCHANT", products=[product]),
    )


def high_value_intent(*, user_authorized_amount, merchant_id="HV-MERCHANT"):
    return IntentMandate(
        merchant_id=merchant_id,
        product_category="laptops",
        max_budget=user_authorized_amount,
        brand="Acme",
        brand_preference="EXACT",
        # The user has already reviewed and selected this exact product
        # (the real /visual-intents/confirm pattern) -- autonomous catalog
        # search is a separate, pre-existing concern (hard budget
        # filtering at discovery time) this task doesn't touch. What's
        # under test here is authorization for an *already-chosen* item.
        autonomous_selection_allowed=False,
    )


def evaluate(*, user_authorized_amount, autonomous_transaction_limit, max_transaction_amount=None):
    contract = high_value_contract(
        autonomous_transaction_limit=autonomous_transaction_limit,
        max_transaction_amount=max_transaction_amount,
    )
    intent = high_value_intent(user_authorized_amount=user_authorized_amount)
    return evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=contract,
        confirmed_product_id="HV-PROD-001",
    )


# ---- A/B/C: user authorization vs. the ₹73,000 purchase, merchant limit generous ----

def test_a_user_authorization_below_purchase_reasks():
    evaluation = evaluate(user_authorized_amount=70_000, autonomous_transaction_limit=100_000)
    assert evaluation.final_decision.decision == DecisionType.REASK


def test_b_user_authorization_equal_to_purchase_continues():
    evaluation = evaluate(user_authorized_amount=73_000, autonomous_transaction_limit=100_000)
    assert evaluation.final_decision.decision == DecisionType.ALLOW


def test_c_user_authorization_above_purchase_continues():
    evaluation = evaluate(user_authorized_amount=90_000, autonomous_transaction_limit=100_000)
    assert evaluation.final_decision.decision == DecisionType.ALLOW


# ---- D/E/F: merchant autonomous limit vs. the ₹73,000 purchase, user authorization generous ----

def test_d_merchant_limit_below_purchase_escalates():
    evaluation = evaluate(user_authorized_amount=100_000, autonomous_transaction_limit=50_000)
    assert evaluation.final_decision.decision == DecisionType.ESCALATE
    assert evaluation.final_decision.reason_code == "MERCHANT_HUMAN_APPROVAL_REQUIRED"
    assert evaluation.merchant_policy.reason_code == "AUTONOMOUS_LIMIT_EXCEEDED"


def test_e_merchant_limit_equal_to_purchase_allows():
    evaluation = evaluate(user_authorized_amount=100_000, autonomous_transaction_limit=73_000)
    assert evaluation.final_decision.decision == DecisionType.ALLOW


def test_f_merchant_limit_above_purchase_allows():
    evaluation = evaluate(user_authorized_amount=100_000, autonomous_transaction_limit=90_000)
    assert evaluation.final_decision.decision == DecisionType.ALLOW


# ---- G/H/I: hard integrity violations always BLOCK, independent of both boundaries ----

def _verified_headphone_purchase(**overrides):
    from backend.app.data.merchants import demo_merchant_contract

    intent_data = {
        "product_category": "headphones",
        "max_budget": 100_000,
        "brand": "Sony",
        "brand_preference": "EXACT",
        "autonomous_selection_allowed": True,
    }
    intent_data.update(overrides.pop("intent_overrides", {}))
    intent = IntentMandate(**intent_data)

    purchase_data = {
        "product_id": "PROD-001",
        "quantity": 1,
        "unit_price": 3200,
        "total_amount": 3200,
        "subscription": False,
    }
    purchase_data.update(overrides)
    purchase = ProposedPurchase(**purchase_data)

    verification = verify_purchase(
        intent,
        purchase,
        demo_merchant_contract.catalog.products,
        selected_product_id="PROD-001",
    )
    return make_decision(verification)


def test_g_price_mismatch_blocks():
    decision = _verified_headphone_purchase(unit_price=1, total_amount=1)
    assert decision["decision"] == DecisionType.BLOCK


def test_h_category_mismatch_blocks():
    decision = _verified_headphone_purchase(
        intent_overrides={
            "product_category": "laptops",
            "max_budget": 100_000,
            "brand": "Sony",
            "brand_preference": "EXACT",
            "autonomous_selection_allowed": True,
        }
    )
    assert decision["decision"] == DecisionType.BLOCK


def test_i_unauthorized_subscription_blocks():
    decision = _verified_headphone_purchase(subscription=True)
    assert decision["decision"] == DecisionType.BLOCK


# ---- J/K/L: the exact spec scenarios ----

def test_j_authorized_80k_limit_50k_purchase_73k_escalates():
    evaluation = evaluate(user_authorized_amount=80_000, autonomous_transaction_limit=50_000)
    assert evaluation.final_decision.decision == DecisionType.ESCALATE
    assert evaluation.final_decision.decision != DecisionType.BLOCK
    assert evaluation.final_decision.decision != DecisionType.REASK
    assert evaluation.ready_for_payment is False


def test_k_authorized_80k_limit_1l_purchase_73k_allows():
    evaluation = evaluate(user_authorized_amount=80_000, autonomous_transaction_limit=100_000)
    assert evaluation.final_decision.decision == DecisionType.ALLOW
    assert evaluation.ready_for_payment is True


def test_l_authorized_70k_purchase_73k_reasks_regardless_of_merchant_limit():
    # The merchant's limit is deliberately generous (₹100,000) to prove
    # the user-authorization check happens first and independently -- a
    # generous merchant limit must never convert an under-authorized
    # purchase into an ESCALATE.
    evaluation = evaluate(user_authorized_amount=70_000, autonomous_transaction_limit=100_000)
    assert evaluation.final_decision.decision == DecisionType.REASK
    assert evaluation.final_decision.decision != DecisionType.ESCALATE


def test_case_4_low_authorization_and_low_merchant_limit_still_reasks_not_escalates():
    """The one case the spec calls out explicitly: do not let an
    under-authorized purchase fall through to ESCALATE just because the
    merchant limit also happens to be low. REASK must win."""
    evaluation = evaluate(user_authorized_amount=70_000, autonomous_transaction_limit=50_000)
    assert evaluation.final_decision.decision == DecisionType.REASK


# ---- O: an expired merchant approval must never allow payment ----

def test_o_expired_merchant_approval_blocks_payment(client, db_session):
    from datetime import datetime, timedelta, timezone

    from backend.app.db.models import MerchantApprovalDB
    from backend.app.services.security_service import hash_password

    password_hash, password_salt = hash_password("expired-approval-test-pw")
    from backend.app.db.models import MerchantCredentialDB

    db_session.add(
        MerchantCredentialDB(
            merchant_id="MERCHANT-001",
            password_hash=password_hash,
            password_salt=password_salt,
        )
    )
    db_session.commit()

    intent_id = client.post(
        "/intents",
        json={
            "product_category": "headphones",
            "max_budget": 10000,
            "quantity": 2,
            "brand": "Sony",
            "brand_preference": "EXACT",
            "preferred_features": ["ANC", "fast charging"],
            "autonomous_selection_allowed": True,
        },
    ).json()["intent_id"]

    request_response = client.post(f"/intents/{intent_id}/merchant-approval")
    assert request_response.status_code == 201
    approval_id = request_response.json()["approval_id"]

    # Force it into the past, exactly like a real approval that timed out
    # before a merchant reviewed it.
    record = (
        db_session.query(MerchantApprovalDB)
        .filter(MerchantApprovalDB.approval_id == approval_id)
        .one()
    )
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    orchestrated = client.post(f"/intents/{intent_id}/orchestrate").json()
    assert orchestrated["evaluation"]["final_decision"]["decision"] == "BLOCK"
    assert (
        orchestrated["evaluation"]["final_decision"]["reason_code"]
        == "MERCHANT_APPROVAL_EXPIRED"
    )
    assert orchestrated["evaluation"]["ready_for_payment"] is False


# ---- P: replaying the same approved payment never creates a second effect ----

def test_p_duplicate_payment_attempt_has_no_duplicate_financial_effect(client, db_session):
    from backend.app.services.security_service import hash_password
    from backend.app.db.models import MerchantCredentialDB

    password_hash, password_salt = hash_password("dup-payment-test-pw")
    db_session.add(
        MerchantCredentialDB(
            merchant_id="MERCHANT-001",
            password_hash=password_hash,
            password_salt=password_salt,
        )
    )
    db_session.commit()

    intent_id = client.post(
        "/intents",
        json={
            "product_category": "headphones",
            "max_budget": 10000,
            "quantity": 2,
            "brand": "Sony",
            "brand_preference": "EXACT",
            "preferred_features": ["ANC", "fast charging"],
            "autonomous_selection_allowed": True,
        },
    ).json()["intent_id"]

    approval_id = client.post(f"/intents/{intent_id}/merchant-approval").json()["approval_id"]
    client.post(
        "/merchant/session/login",
        json={"merchant_id": "MERCHANT-001", "password": "dup-payment-test-pw"},
    )
    decision_body = client.post(
        f"/merchant/approvals/{approval_id}/decision",
        json={"decision": "APPROVE", "reason": "ok"},
    ).json()
    purchase = decision_body["evaluation"]["buyer_agent"]["proposed_purchase"]

    first = client.post(
        "/payments/create",
        json={"intent_id": intent_id, "purchase": purchase, "idempotency_key": "dup-key-001"},
    )
    second = client.post(
        "/payments/create",
        json={"intent_id": intent_id, "purchase": purchase, "idempotency_key": "dup-key-001"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["payment_created"] is True
    assert second.json()["payment_created"] is False
    assert (
        first.json()["payment_result"]["payment"]["payment_id"]
        == second.json()["payment_result"]["payment"]["payment_id"]
    )
