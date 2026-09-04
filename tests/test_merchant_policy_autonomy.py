import pytest

from backend.app.schemas.merchant_policy import MerchantPolicy
from backend.app.services.merchant_policy_engine import evaluate_merchant_policy


def verified(expected_total):
    return {"verified": True, "expected_total": expected_total, "violations": []}


def test_within_autonomous_limit_and_daily_caps_is_approved():
    policy = MerchantPolicy(
        merchant_id="MERCHANT-001",
        autonomous_transaction_limit=3500,
        daily_autonomous_amount_limit=50000,
        daily_autonomous_transaction_limit=20,
    )

    result = evaluate_merchant_policy(
        verified(3200),
        policy,
        autonomous_usage_today=(10000, 5),
    )

    assert result["status"] == "APPROVED"
    assert result["reason_code"] == "MERCHANT_POLICY_PASSED"


def test_above_autonomous_limit_escalates_by_default():
    policy = MerchantPolicy(
        merchant_id="MERCHANT-001",
        autonomous_transaction_limit=3500,
    )

    result = evaluate_merchant_policy(verified(5500), policy)

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["requires_human_approval"] is True
    assert result["reason_code"] == "AUTONOMOUS_LIMIT_EXCEEDED"
    assert result["threshold"] == 3500
    assert result["amount"] == 5500


def test_above_autonomous_limit_rejects_when_merchant_opts_out_of_review():
    policy = MerchantPolicy(
        merchant_id="MERCHANT-001",
        autonomous_transaction_limit=3500,
        require_human_review_for_policy_exceptions=False,
    )

    result = evaluate_merchant_policy(verified(5500), policy)

    assert result["status"] == "REJECTED"
    assert result["requires_human_approval"] is False
    assert result["reason_code"] == "AUTONOMOUS_LIMIT_EXCEEDED"


def test_daily_amount_cap_breach_escalates_even_within_per_transaction_limit():
    policy = MerchantPolicy(
        merchant_id="MERCHANT-001",
        autonomous_transaction_limit=3500,
        daily_autonomous_amount_limit=10000,
    )

    # A small, individually-fine ₹3000 purchase, but ₹8000 was already
    # spent autonomously today -- 8000 + 3000 > 10000.
    result = evaluate_merchant_policy(
        verified(3000),
        policy,
        autonomous_usage_today=(8000, 3),
    )

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["reason_code"] == "DAILY_AUTONOMOUS_LIMIT_EXCEEDED"


def test_daily_transaction_count_cap_breach_escalates():
    policy = MerchantPolicy(
        merchant_id="MERCHANT-001",
        autonomous_transaction_limit=3500,
        daily_autonomous_transaction_limit=5,
    )

    result = evaluate_merchant_policy(
        verified(100),
        policy,
        autonomous_usage_today=(500, 5),
    )

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["reason_code"] == "DAILY_AUTONOMOUS_LIMIT_EXCEEDED"


def test_high_value_review_threshold_escalates_within_autonomous_limit():
    policy = MerchantPolicy(
        merchant_id="MERCHANT-001",
        autonomous_transaction_limit=10000,
        high_value_review_threshold=3000,
    )

    # Within the ₹10,000 autonomous envelope, but above the merchant's
    # own stricter ₹3,000 high-value bar.
    result = evaluate_merchant_policy(verified(4000), policy)

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["reason_code"] == "HIGH_VALUE_REVIEW_REQUIRED"


def test_high_value_review_threshold_cannot_exceed_autonomous_limit():
    with pytest.raises(Exception, match="cannot exceed the autonomous transaction limit"):
        MerchantPolicy(
            merchant_id="MERCHANT-001",
            autonomous_transaction_limit=3000,
            high_value_review_threshold=4000,
        )
