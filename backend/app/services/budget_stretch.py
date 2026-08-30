from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.product import Product


MAX_STRETCH_PERCENT = 15
MIN_RATING_GAIN = 0.1
MIN_NEW_FEATURES = 2


def find_budget_stretch_candidates(
    intent: IntentMandate,
    allowed_products: list[Product],
    rejected_products: list[dict]
):
    stretch_candidates = []

    if not allowed_products:
        return stretch_candidates

    baseline_product = max(
        allowed_products,
        key=lambda product: product.rating
    )

    for rejected_item in rejected_products:
        product = rejected_item["product"]
        proposed_total = product.price * intent.quantity

        rejection_codes = {
            reason["code"]
            for reason in rejected_item["reasons"]
        }

        if rejection_codes != {"BUDGET_EXCEEDED"}:
            continue

        over_budget_amount = proposed_total - intent.max_budget

        over_budget_percent = (
            over_budget_amount / intent.max_budget
        ) * 100

        if over_budget_percent > MAX_STRETCH_PERCENT:
            continue

        new_features = [
            feature
            for feature in product.features
            if feature not in baseline_product.features
        ]

        rating_gain = product.rating - baseline_product.rating

        meaningful_upgrade = (
            rating_gain >= MIN_RATING_GAIN
            or len(new_features) >= MIN_NEW_FEATURES
        )

        if not meaningful_upgrade:
            continue

        stretch_candidates.append({
            "product": product,
            "decision": "REASK",
            "over_budget_amount": over_budget_amount,
            "over_budget_percent": round(over_budget_percent, 2),
            "proposed_total": proposed_total,
            "compared_with": baseline_product.product_id,
            "rating_gain": round(rating_gain, 2),
            "new_features": new_features,
            "message": (
                f"This product is ₹{over_budget_amount} above budget "
                f"but provides meaningful additional value. "
                f"User approval is required."
            )
        })

    return stretch_candidates
