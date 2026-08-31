from backend.app.schemas.buyer_agent import BuyerAgentResult
from backend.app.schemas.decision import DecisionType
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.product import Product
from backend.app.schemas.purchase import ProposedPurchase

from backend.app.services.budget_stretch import (
    find_budget_stretch_candidates,
)
from backend.app.services.preference_engine import rank_products
from backend.app.services.product_filter import filter_products
from backend.app.services.tradeoff_engine import evaluate_tradeoff


def run_buyer_agent(
    intent: IntentMandate,
    products: list[Product],
    confirmed_product_id: str | None = None,
) -> BuyerAgentResult:
    # --------------------------------------------------------
    # 1. Apply hard user constraints
    # --------------------------------------------------------

    allowed_products, rejected_products = filter_products(
        intent,
        products,
    )

    # --------------------------------------------------------
    # 2. Rank only products that passed hard constraints
    # --------------------------------------------------------

    ranked_products = rank_products(
        intent,
        allowed_products,
    )

    # --------------------------------------------------------
    # 3. Find useful above-budget recommendations
    # --------------------------------------------------------

    stretch_candidates = find_budget_stretch_candidates(
        intent,
        allowed_products,
        rejected_products,
    )

    # --------------------------------------------------------
    # 4. Stop when no valid product exists
    # --------------------------------------------------------

    if not ranked_products:
        return BuyerAgentResult(
            decision=DecisionType.BLOCK,
            reason_code="NO_VALID_PRODUCT",
            message=(
                "No product satisfies the current "
                "intent and authorization."
            ),
            rejected_products=rejected_products,
            stretch_candidates=stretch_candidates,
        )

    recommended_product = ranked_products[0]["product"]

    alternative_products = [
        ranked_result["product"]
        for ranked_result in ranked_products[1:]
    ]

    # --------------------------------------------------------
    # 5. Detect meaningful price/value trade-offs
    # --------------------------------------------------------

    tradeoff_result = evaluate_tradeoff(
        intent,
        ranked_products,
    )

    # --------------------------------------------------------
    # 6. Respect an explicit user-confirmed product
    # --------------------------------------------------------

    if confirmed_product_id is not None:
        selected_product = next(
            (
                product
                for product in allowed_products
                if product.product_id == confirmed_product_id
            ),
            None,
        )

        if selected_product is None:
            return BuyerAgentResult(
                decision=DecisionType.REASK,
                reason_code="CONFIRMED_PRODUCT_NOT_AVAILABLE",
                message=(
                    "The previously confirmed product is no "
                    "longer valid for the current intent."
                ),
                recommended_product=recommended_product,
                alternative_products=alternative_products,
                ranked_products=ranked_products,
                rejected_products=rejected_products,
                stretch_candidates=stretch_candidates,
            )

    # --------------------------------------------------------
    # 7. Ask the user when autonomous selection is disabled
    # --------------------------------------------------------

    elif not intent.autonomous_selection_allowed:
        reason_code = "USER_SELECTION_REQUIRED"
        message = (
            "The user must confirm a product before "
            "a purchase can be proposed."
        )

        if (
            tradeoff_result["decision"]
            == DecisionType.REASK
        ):
            reason_code = tradeoff_result["reason_code"]
            message = tradeoff_result["message"]

        return BuyerAgentResult(
            decision=DecisionType.REASK,
            reason_code=reason_code,
            message=message,
            recommended_product=recommended_product,
            alternative_products=alternative_products,
            ranked_products=ranked_products,
            rejected_products=rejected_products,
            stretch_candidates=stretch_candidates,
        )

    # --------------------------------------------------------
    # 8. Autonomous selection is explicitly authorized
    # --------------------------------------------------------

    else:
        selected_product = recommended_product

    # --------------------------------------------------------
    # 9. Create the exact transaction proposal
    # --------------------------------------------------------

    proposed_purchase = ProposedPurchase(
        product_id=selected_product.product_id,
        quantity=intent.quantity,
        unit_price=selected_product.price,
        total_amount=(
            selected_product.price
            * intent.quantity
        ),
        subscription=False,
    )

    return BuyerAgentResult(
        decision=DecisionType.ALLOW,
        reason_code="PURCHASE_PROPOSAL_CREATED",
        message=(
            "The Buyer Agent created a purchase proposal. "
            "The proposal must still pass the Trust Gate."
        ),
        recommended_product=recommended_product,
        selected_product=selected_product,
        alternative_products=[
            product
            for product in alternative_products
            if product.product_id != selected_product.product_id
        ],
        ranked_products=ranked_products,
        rejected_products=rejected_products,
        stretch_candidates=stretch_candidates,
        proposed_purchase=proposed_purchase,
    )
