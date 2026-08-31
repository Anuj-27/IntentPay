from backend.app.schemas.buyer_agent import BuyerAgentResult
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.safety import (
    RecommendationIntegrityResult,
    SafetyControl,
    SafetyControlStatus,
    SafetyManifest,
)


def build_safety_manifest() -> SafetyManifest:
    enforced = SafetyControlStatus.ENFORCED

    return SafetyManifest(
        privacy_mode="MINIMIZE_AND_REDACT",
        controls=[
            SafetyControl(
                control_id="PERSISTED_INTENT_AUTHORITY",
                status=enforced,
                description=(
                    "Payment authorization is rebuilt from the persisted "
                    "intent rather than a caller-supplied replacement."
                ),
                evidence=["POST /payments/create"],
            ),
            SafetyControl(
                control_id="HARD_CONSTRAINTS_BEFORE_RANKING",
                status=enforced,
                description=(
                    "Category, budget, stock, and exact preferences are "
                    "filtered before product ranking."
                ),
                evidence=["backend/app/services/product_filter.py"],
            ),
            SafetyControl(
                control_id="FINAL_TRANSACTION_REVERIFICATION",
                status=enforced,
                description=(
                    "The exact quantity, catalog price, total, product, and "
                    "subscription flag are verified before payment."
                ),
                evidence=["backend/app/services/intent_verifier.py"],
            ),
            SafetyControl(
                control_id="RECOMMENDATION_INTEGRITY",
                status=enforced,
                description=(
                    "Recommendations and proposals are checked against the "
                    "ranked valid set and user authorization."
                ),
                evidence=["POST /intents/{intent_id}/orchestrate"],
            ),
            SafetyControl(
                control_id="MERCHANT_POLICY_SEPARATION",
                status=enforced,
                description=(
                    "Merchant permission is evaluated separately from user "
                    "authorization and cannot override it."
                ),
                evidence=["backend/app/services/trust_gate.py"],
            ),
            SafetyControl(
                control_id="IDEMPOTENT_PAYMENT_CREATION",
                status=enforced,
                description=(
                    "One idempotency key cannot create multiple logical "
                    "payment records."
                ),
                evidence=["backend/app/services/payment_service.py"],
            ),
            SafetyControl(
                control_id="UNKNOWN_PAYMENT_RECONCILIATION",
                status=enforced,
                description=(
                    "Uncertain payments enter UNKNOWN and must be reconciled "
                    "instead of being blindly retried."
                ),
                evidence=["POST /payments/{payment_id}/reconcile"],
            ),
            SafetyControl(
                control_id="AUDIT_SECRET_REDACTION",
                status=enforced,
                description=(
                    "Known credential, signature, token, and idempotency fields "
                    "are recursively redacted before audit persistence."
                ),
                evidence=["backend/app/services/privacy_service.py"],
            ),
            SafetyControl(
                control_id="SAFE_HTTP_RESPONSE_HEADERS",
                status=enforced,
                description=(
                    "API responses disable MIME sniffing, framing, referrer "
                    "leakage, and sensitive response caching."
                ),
                evidence=["backend/app/main.py"],
            ),
        ],
        limitations=[
            "The development API does not yet implement user authentication or authorization.",
            "Audit records are mutable database rows, not a cryptographically immutable ledger.",
            "Razorpay Test Mode requires user-supplied test credentials and a public webhook URL.",
            "Only Razorpay test keys are accepted; live-money execution is intentionally rejected.",
            "No live-money payment execution is enabled.",
        ],
    )


def evaluate_recommendation_integrity(
    intent: IntentMandate,
    buyer_result: BuyerAgentResult,
    confirmed_product_id: str | None = None,
) -> RecommendationIntegrityResult:
    violations = []
    ranked_products = [
        ranked.product
        for ranked in buyer_result.ranked_products
    ]
    ranked_ids = [product.product_id for product in ranked_products]

    recommended_product_id = (
        buyer_result.recommended_product.product_id
        if buyer_result.recommended_product is not None
        else None
    )

    cheapest_product = (
        min(
            ranked_products,
            key=lambda product: product.price * intent.quantity,
        )
        if ranked_products
        else None
    )

    if len(ranked_ids) != len(set(ranked_ids)):
        violations.append({
            "code": "DUPLICATE_RANKED_PRODUCT",
            "message": "The ranked product list contains duplicate products.",
        })

    if ranked_products:
        expected_recommendation_id = ranked_products[0].product_id

        if recommended_product_id != expected_recommendation_id:
            violations.append({
                "code": "TOP_RANKED_PRODUCT_NOT_RECOMMENDED",
                "message": (
                    "The recommendation does not match the deterministic "
                    "top-ranked valid product."
                ),
            })
    elif buyer_result.recommended_product is not None:
        violations.append({
            "code": "RECOMMENDATION_WITHOUT_VALID_PRODUCT",
            "message": "A product was recommended when no valid product exists.",
        })

    surfaced_ids = {
        product.product_id
        for product in buyer_result.alternative_products
    }
    if recommended_product_id is not None:
        surfaced_ids.add(recommended_product_id)
    if buyer_result.selected_product is not None:
        surfaced_ids.add(buyer_result.selected_product.product_id)

    if (
        cheapest_product is not None
        and cheapest_product.product_id not in surfaced_ids
    ):
        violations.append({
            "code": "CHEAPEST_VALID_OPTION_HIDDEN",
            "message": "The cheapest valid product was not surfaced to the user.",
        })

    purchase = buyer_result.proposed_purchase

    if purchase is not None:
        if purchase.product_id not in ranked_ids:
            violations.append({
                "code": "PROPOSED_PRODUCT_NOT_VALID",
                "message": "The proposed product is not in the ranked valid set.",
            })

        if (
            buyer_result.selected_product is None
            or buyer_result.selected_product.product_id != purchase.product_id
        ):
            violations.append({
                "code": "SELECTED_PRODUCT_MISMATCH",
                "message": "The selected product does not match the proposal.",
            })

        if purchase.total_amount > intent.max_budget:
            violations.append({
                "code": "ABOVE_BUDGET_PROPOSAL",
                "message": "An above-budget recommendation became a purchase proposal.",
            })

        if purchase.quantity != intent.quantity:
            violations.append({
                "code": "PROPOSAL_QUANTITY_MISMATCH",
                "message": "The proposal quantity differs from the authorized quantity.",
            })

        if purchase.subscription and not intent.subscription_allowed:
            violations.append({
                "code": "UNAUTHORIZED_SUBSCRIPTION_PROPOSAL",
                "message": "The proposal contains an unauthorized subscription.",
            })

        if (
            not intent.autonomous_selection_allowed
            and confirmed_product_id != purchase.product_id
        ):
            violations.append({
                "code": "UNCONFIRMED_PRODUCT_PROPOSAL",
                "message": "The proposal was not explicitly selected by the user.",
            })

    recommended_price_premium = None
    if buyer_result.recommended_product is not None and cheapest_product is not None:
        recommended_price_premium = (
            buyer_result.recommended_product.price
            - cheapest_product.price
        ) * intent.quantity

    return RecommendationIntegrityResult(
        verified=not violations,
        reason_code=(
            "RECOMMENDATION_INTEGRITY_PASSED"
            if not violations
            else "RECOMMENDATION_INTEGRITY_FAILED"
        ),
        cheapest_valid_product_id=(
            cheapest_product.product_id
            if cheapest_product is not None
            else None
        ),
        recommended_product_id=recommended_product_id,
        recommended_price_premium=recommended_price_premium,
        violations=violations,
    )
