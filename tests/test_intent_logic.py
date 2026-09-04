from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.data.products import products
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.product import Product
from backend.app.services.intent_extractor import extract_intent_from_text
from backend.app.services.llm_intent_extractor import extract_intent_with_llm
from backend.app.services.preference_engine import rank_products
from backend.app.services.product_filter import filter_products


def test_parser_handles_indian_budget_format_and_quantity():
    intent = extract_intent_from_text(
        "Buy 2 Sony black headphones under ₹5,000. No subscription."
    )

    assert intent.max_budget == 5000
    assert intent.quantity == 2
    assert intent.brand == "Sony"
    assert intent.brand_preference == "EXACT"
    assert intent.color == "black"
    assert intent.color_preference == "EXACT"
    assert intent.subscription_allowed is False


def test_parser_handles_explicit_quantity_phrasing():
    intent = extract_intent_from_text(
        "make quantity 2, still want sony headphones under 7000"
    )

    assert intent.quantity == 2


def test_parser_distinguishes_preference_from_requirement():
    intent = extract_intent_from_text(
        "I prefer Sony headphones, budget of INR 5000."
    )

    assert intent.brand_preference == "PREFERRED"


def test_filter_uses_quantity_aware_total():
    intent = IntentMandate(
        product_category="headphones",
        max_budget=5000,
        quantity=2,
    )

    allowed, rejected = filter_products(intent, products)

    assert allowed == []
    assert all(
        "BUDGET_EXCEEDED" in {reason["code"] for reason in item["reasons"]}
        for item in rejected
    )


def test_filter_keeps_the_explicit_budget_as_a_hard_boundary():
    intent = IntentMandate(
        merchant_id="MERCHANT-002",
        product_category="smartphones",
        max_budget=69900,
    )
    products_for_budget_test = [
        Product(
            product_id="PHONE-IN",
            name="Phone in budget",
            category="smartphones",
            price=69900,
            brand="Example",
            rating=4.0,
        ),
        Product(
            product_id="PHONE-OUT",
            name="Phone above budget",
            category="smartphones",
            price=73000,
            brand="Example",
            rating=4.0,
        ),
    ]

    allowed, rejected = filter_products(intent, products_for_budget_test)

    assert [product.product_id for product in allowed] == ["PHONE-IN"]
    above_budget = next(item for item in rejected if item["product"].product_id == "PHONE-OUT")
    assert {reason["code"] for reason in above_budget["reasons"]} == {"BUDGET_EXCEEDED"}


def test_case_is_normalized_for_exact_constraints():
    intent = IntentMandate(
        product_category="Headphones",
        max_budget=5000,
        brand="sony",
        brand_preference="EXACT",
        color="Black",
        color_preference="EXACT",
    )

    allowed, _ = filter_products(intent, products)

    assert [product.product_id for product in allowed] == ["PROD-001", "PROD-002"]


def test_preferred_brand_affects_ranking():
    intent = IntentMandate(
        product_category="headphones",
        max_budget=5000,
        brand="Sony",
        brand_preference="PREFERRED",
    )
    allowed, _ = filter_products(intent, products)

    ranked = rank_products(intent, allowed)

    assert ranked[0]["product"].brand == "Sony"
    assert ranked[0]["score_breakdown"]["brand_preference_score"] > 0


def test_invalid_priority_is_rejected():
    with pytest.raises(ValidationError):
        IntentMandate(
            product_category="headphones",
            max_budget=5000,
            priority="NOT_A_REAL_PRIORITY",
        )


class FakeResponses:
    def __init__(self, intent):
        self.intent = intent

    def parse(self, **_kwargs):
        return SimpleNamespace(output_parsed=self.intent)


class FakeOpenAIClient:
    def __init__(self, intent):
        self.responses = FakeResponses(intent)


def test_llm_extractor_rejects_invented_authorization():
    invented = IntentMandate(
        product_category="headphones",
        max_budget=9000,
        subscription_allowed=True,
    )

    with pytest.raises(ValueError, match="budget"):
        extract_intent_with_llm(
            "Buy headphones under ₹5,000",
            client=FakeOpenAIClient(invented),
        )


def test_llm_extractor_accepts_matching_structured_output():
    expected = IntentMandate(
        product_category="headphones",
        max_budget=5000,
        quantity=2,
    )

    result = extract_intent_with_llm(
        "Buy 2 headphones under ₹5,000",
        client=FakeOpenAIClient(expected),
    )

    assert result == expected
