import pytest
from pydantic import ValidationError

from backend.app.data.merchants import demo_merchant_contract
from backend.app.schemas.decision import DecisionType
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.merchant import (
    MerchantCapabilities,
    MerchantCatalog,
    MerchantContract,
)
from backend.app.schemas.merchant_policy import MerchantPolicy
from backend.app.services.buyer_agent import run_buyer_agent
from backend.app.services.merchant_policy_engine import (
    evaluate_merchant_policy,
)
from backend.app.services.merchant_service import find_merchant_contract
from backend.app.services.trust_gate import evaluate_trust_gate


def autonomous_intent(**overrides) -> IntentMandate:
    intent_data = {
        "product_category": "headphones",
        "max_budget": 5000,
        "brand": "Sony",
        "brand_preference": "EXACT",
        "autonomous_selection_allowed": True,
        "preferred_features": ["ANC", "fast charging"],
    }
    intent_data.update(overrides)
    return IntentMandate(**intent_data)


def test_merchant_capabilities_fail_closed_by_default():
    capabilities = MerchantCapabilities()

    assert capabilities.catalog_search is False
    assert capabilities.inventory_check is False
    assert capabilities.checkout is False
    assert capabilities.refunds is False


def test_merchant_contract_rejects_mismatched_catalog():
    contract_data = demo_merchant_contract.model_dump()
    contract_data["catalog"]["merchant_id"] = "OTHER-MERCHANT"

    with pytest.raises(
        ValidationError,
        match="catalog belongs to a different merchant",
    ):
        MerchantContract.model_validate(contract_data)


def test_merchant_catalog_rejects_duplicate_product_ids():
    product = demo_merchant_contract.catalog.products[0]

    with pytest.raises(
        ValidationError,
        match="duplicate product IDs",
    ):
        MerchantCatalog(
            merchant_id="MERCHANT-001",
            products=[product, product],
        )


def test_merchant_policy_rejects_contradictory_thresholds():
    with pytest.raises(
        ValidationError,
        match="approval threshold cannot exceed",
    ):
        MerchantPolicy(
            merchant_id="MERCHANT-001",
            max_transaction_amount=5000,
            human_approval_threshold=6000,
        )


def test_merchant_service_returns_defensive_copy():
    first = find_merchant_contract("MERCHANT-001")
    second = find_merchant_contract("MERCHANT-001")

    assert first is not None
    assert second is not None

    first.merchant.active = False

    assert second.merchant.active is True


def test_buyer_agent_blocks_inactive_merchant():
    contract = demo_merchant_contract.model_copy(deep=True)
    contract.merchant.active = False

    result = run_buyer_agent(
        autonomous_intent(),
        contract,
    )

    assert result.decision == DecisionType.BLOCK
    assert result.reason_code == "MERCHANT_INACTIVE"
    assert result.proposed_purchase is None


def test_buyer_agent_blocks_when_checkout_is_unavailable():
    contract = demo_merchant_contract.model_copy(deep=True)
    contract.merchant.capabilities.checkout = False

    result = run_buyer_agent(
        autonomous_intent(),
        contract,
    )

    assert result.decision == DecisionType.BLOCK
    assert result.reason_code == "MERCHANT_CHECKOUT_UNAVAILABLE"
    assert result.recommended_product is not None
    assert result.selected_product is not None
    assert result.proposed_purchase is None


def test_buyer_agent_blocks_merchant_intent_mismatch():
    result = run_buyer_agent(
        autonomous_intent(merchant_id="OTHER-MERCHANT"),
        demo_merchant_contract,
    )

    assert result.decision == DecisionType.BLOCK
    assert result.reason_code == "MERCHANT_INTENT_MISMATCH"
    assert result.proposed_purchase is None


def test_hard_merchant_transaction_limit_blocks_purchase():
    policy = MerchantPolicy(
        merchant_id="MERCHANT-001",
        max_transaction_amount=3000,
        human_approval_threshold=2000,
    )
    verification_result = {
        "verified": True,
        "expected_total": 3200,
        "violations": [],
    }

    policy_result = evaluate_merchant_policy(
        verification_result,
        policy,
    )
    final_decision = evaluate_trust_gate(
        {
            "decision": DecisionType.ALLOW,
            "reason_code": "INTENT_VERIFIED",
            "message": "Intent verified.",
        },
        policy_result,
    )

    assert policy_result["status"] == "REJECTED"
    assert (
        policy_result["reason_code"]
        == "MERCHANT_TRANSACTION_LIMIT_EXCEEDED"
    )
    assert final_decision["decision"] == DecisionType.BLOCK
    assert (
        final_decision["reason_code"]
        == "MERCHANT_TRANSACTION_LIMIT_EXCEEDED"
    )
