from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.decision import DecisionType


MEANINGFUL_PRICE_DIFFERENCE_PERCENT = 20


def evaluate_tradeoff(
    intent: IntentMandate,
    ranked_products: list[dict]
):
    if not ranked_products:
        return {
            "decision": DecisionType.BLOCK,
            "reason_code": "NO_VALID_PRODUCT",
            "message": "No product satisfies the current intent."
        }

    top_product = ranked_products[0]["product"]

    if len(ranked_products) == 1:
        return {
            "decision": DecisionType.ALLOW,
            "reason_code": "SINGLE_VALID_OPTION",
            "recommended_product": top_product
        }

    second_product = ranked_products[1]["product"]

    top_total = top_product.price * intent.quantity
    second_total = second_product.price * intent.quantity
    price_difference = top_total - second_total

    if second_total > 0:
        price_difference_percent = (
            price_difference / second_total
        ) * 100
    else:
        price_difference_percent = 0

    meaningful_price_tradeoff = (
        price_difference > 0
        and price_difference_percent
        >= MEANINGFUL_PRICE_DIFFERENCE_PERCENT
    )

    if (
        meaningful_price_tradeoff
        and not intent.autonomous_selection_allowed
    ):
        return {
            "decision": DecisionType.REASK,
            "reason_code": "MEANINGFUL_PRICE_VALUE_TRADEOFF",
            "recommended_product": top_product,
            "alternative_product": second_product,
            "price_difference": price_difference,
            "price_difference_percent": round(
                price_difference_percent,
                2
            ),
            "message": (
                "The recommended product provides better value "
                "but costs significantly more than another valid option. "
                "User confirmation is required."
            )
        }

    return {
        "decision": DecisionType.ALLOW,
        "reason_code": "TOP_RANKED_OPTION",
        "recommended_product": top_product
    }
