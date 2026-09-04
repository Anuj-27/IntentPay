from backend.app.data.merchants import demo_merchant_contract
from backend.app.schemas.decision import DecisionType
from backend.app.schemas.intent import IntentMandate
from backend.app.services.buyer_agent import run_buyer_agent


products = demo_merchant_contract.catalog.products


def build_intent(**overrides) -> IntentMandate:
    intent_data = {
        "product_category": "headphones",
        "max_budget": 5000,
        "quantity": 1,
        "brand": "Sony",
        "brand_preference": "EXACT",
        "subscription_allowed": False,
        "autonomous_selection_allowed": False,
        "priority": "BEST_VALUE",
        "preferred_features": [
            "ANC",
            "fast charging",
        ],
    }

    intent_data.update(overrides)

    return IntentMandate(**intent_data)


def test_autonomous_agent_creates_proposal():
    intent = build_intent(
        autonomous_selection_allowed=True,
    )

    result = run_buyer_agent(
        intent,
        demo_merchant_contract,
    )

    assert result.decision == DecisionType.ALLOW
    assert result.reason_code == "PURCHASE_PROPOSAL_CREATED"

    assert result.proposed_purchase is not None
    assert result.proposed_purchase.product_id == "PROD-002"
    assert result.proposed_purchase.total_amount == 4800


def test_non_autonomous_agent_requires_user_selection():
    intent = build_intent(
        autonomous_selection_allowed=False,
    )

    result = run_buyer_agent(
        intent,
        demo_merchant_contract,
    )

    assert result.decision == DecisionType.REASK
    assert (
        result.reason_code
        == "MEANINGFUL_PRICE_VALUE_TRADEOFF"
    )

    assert result.recommended_product is not None
    assert result.recommended_product.product_id == "PROD-002"
    assert result.proposed_purchase is None


def test_confirmed_product_is_respected():
    intent = build_intent(
        autonomous_selection_allowed=False,
    )

    result = run_buyer_agent(
        intent,
        demo_merchant_contract,
        confirmed_product_id="PROD-001",
    )

    assert result.decision == DecisionType.ALLOW
    assert result.proposed_purchase is not None
    assert result.recommended_product is not None
    assert result.selected_product is not None

    # Keep the agent's recommendation distinct from the user's choice.
    assert result.recommended_product.product_id == "PROD-002"
    assert result.selected_product.product_id == "PROD-001"

    assert (
        result.proposed_purchase.product_id
        == "PROD-001"
    )

    assert result.proposed_purchase.total_amount == 3200


def test_invalid_confirmed_product_requires_reask():
    intent = build_intent(
        autonomous_selection_allowed=False,
    )

    result = run_buyer_agent(
        intent,
        demo_merchant_contract,
        confirmed_product_id="PROD-003",
    )

    assert result.decision == DecisionType.REASK
    assert (
        result.reason_code
        == "CONFIRMED_PRODUCT_NOT_AVAILABLE"
    )

    assert result.proposed_purchase is None


def test_no_valid_product_is_blocked():
    intent = build_intent(
        color="white",
        color_preference="EXACT",
    )

    result = run_buyer_agent(
        intent,
        demo_merchant_contract,
    )

    assert result.decision == DecisionType.BLOCK
    assert result.reason_code == "NO_VALID_PRODUCT"

    assert result.recommended_product is None
    assert result.proposed_purchase is None
    assert len(result.rejected_products) == len(products)


def test_proposed_total_uses_quantity():
    intent = build_intent(
        max_budget=10000,
        quantity=2,
        autonomous_selection_allowed=True,
    )

    result = run_buyer_agent(
        intent,
        demo_merchant_contract,
    )

    assert result.decision == DecisionType.ALLOW
    assert result.proposed_purchase is not None
    assert result.selected_product is not None

    assert result.proposed_purchase.product_id == "PROD-002"
    assert result.selected_product.product_id == "PROD-002"
    assert result.proposed_purchase.quantity == 2
    assert result.proposed_purchase.unit_price == 4800
    assert result.proposed_purchase.total_amount == 9600

    # Buyer Agent must never invent a subscription.
    assert result.proposed_purchase.subscription is False


def test_budget_stretch_candidate_is_exposed():
    intent = build_intent(
        autonomous_selection_allowed=False,
    )

    result = run_buyer_agent(
        intent,
        demo_merchant_contract,
    )

    stretch_product_ids = {
        candidate.product.product_id
        for candidate in result.stretch_candidates
    }

    assert "PROD-004" in stretch_product_ids
    assert all(
        candidate.status == "REQUIRES_REAUTHORIZATION"
        for candidate in result.stretch_candidates
    )

    # Stretch recommendations are not purchase authorization.
    assert result.proposed_purchase is None
