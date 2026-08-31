from backend.app.schemas.decision import DecisionType
from backend.app.schemas.evaluation import EvaluationCase
from backend.app.schemas.intent import IntentMandate


DATASET_NAME = "IntentPay Deterministic Safety Benchmark"
DATASET_VERSION = "1.0"


def make_intent(
    *,
    max_budget: int,
    category: str = "headphones",
    autonomous: bool = False,
    priority: str = "BEST_VALUE",
    preferred_features: list[str] | None = None,
) -> IntentMandate:
    return IntentMandate(
        product_category=category,
        max_budget=max_budget,
        brand="Sony",
        brand_preference="EXACT",
        subscription_allowed=False,
        autonomous_selection_allowed=autonomous,
        priority=priority,
        preferred_features=(
            preferred_features
            if preferred_features is not None
            else ["ANC", "fast charging"]
        ),
    )


def build_evaluation_cases() -> list[EvaluationCase]:
    cases = []

    for index in range(100):
        cases.append(EvaluationCase(
            case_id=f"allow-confirmed-basic-{index + 1:03d}",
            category="VALID_CONFIRMED_PURCHASE",
            intent=make_intent(max_budget=3200 + index * 5),
            confirmed_product_id="PROD-001",
            expected_decision=DecisionType.ALLOW,
            expected_reason_code="TRUST_GATE_PASSED",
            expected_product_id="PROD-001",
        ))

    for index in range(75):
        cases.append(EvaluationCase(
            case_id=f"reask-meaningful-tradeoff-{index + 1:03d}",
            category="MEANINGFUL_PRICE_VALUE_TRADEOFF",
            intent=make_intent(max_budget=4800 + index),
            expected_decision=DecisionType.REASK,
            expected_reason_code="MEANINGFUL_PRICE_VALUE_TRADEOFF",
            expected_product_id="PROD-002",
        ))

    for index in range(75):
        cases.append(EvaluationCase(
            case_id=f"block-budget-no-product-{index + 1:03d}",
            category="NO_PRODUCT_WITHIN_BUDGET",
            intent=make_intent(max_budget=2000 + index * 10),
            expected_decision=DecisionType.BLOCK,
            expected_reason_code="NO_VALID_PRODUCT",
        ))

    for index in range(75):
        cases.append(EvaluationCase(
            case_id=f"escalate-merchant-threshold-{index + 1:03d}",
            category="MERCHANT_APPROVAL_REQUIRED",
            intent=make_intent(
                max_budget=4800 + index,
                autonomous=True,
            ),
            expected_decision=DecisionType.ESCALATE,
            expected_reason_code="MERCHANT_HUMAN_APPROVAL_REQUIRED",
            expected_product_id="PROD-002",
        ))

    for index in range(50):
        cases.append(EvaluationCase(
            case_id=f"block-wrong-category-{index + 1:03d}",
            category="CATEGORY_MISMATCH",
            intent=make_intent(
                max_budget=5000 + index,
                category=f"laptop-{index + 1}",
            ),
            expected_decision=DecisionType.BLOCK,
            expected_reason_code="NO_VALID_PRODUCT",
        ))

    for index in range(50):
        cases.append(EvaluationCase(
            case_id=f"reask-invalid-confirmation-{index + 1:03d}",
            category="CONFIRMED_PRODUCT_NOT_VALID",
            intent=make_intent(max_budget=4800 + index),
            confirmed_product_id="PROD-003",
            expected_decision=DecisionType.REASK,
            expected_reason_code="CONFIRMED_PRODUCT_NOT_AVAILABLE",
            expected_product_id="PROD-002",
        ))

    for index in range(50):
        cases.append(EvaluationCase(
            case_id=f"allow-cheapest-autonomous-{index + 1:03d}",
            category="AUTHORIZED_CHEAPEST_SELECTION",
            intent=make_intent(
                max_budget=4800 + index,
                autonomous=True,
                priority="CHEAPEST",
                preferred_features=[],
            ),
            expected_decision=DecisionType.ALLOW,
            expected_reason_code="TRUST_GATE_PASSED",
            expected_product_id="PROD-001",
        ))

    for index in range(25):
        cases.append(EvaluationCase(
            case_id=f"reask-single-option-{index + 1:03d}",
            category="USER_SELECTION_REQUIRED",
            intent=make_intent(max_budget=3200 + index),
            expected_decision=DecisionType.REASK,
            expected_reason_code="USER_SELECTION_REQUIRED",
            expected_product_id="PROD-001",
        ))

    return cases


evaluation_cases = build_evaluation_cases()

