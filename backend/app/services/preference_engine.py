from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.product import Product


def calculate_feature_match(
    preferred_features: list[str],
    product: Product
) -> tuple[int, list[str]]:

    matched_features = []

    for preferred_feature in preferred_features:
        for product_feature in product.features:

            if preferred_feature.lower() in product_feature.lower():
                matched_features.append(preferred_feature)
                break

    return len(matched_features), matched_features


def calculate_preference_score(
    intent: IntentMandate,
    product: Product,
):
    brand_score = 0
    color_score = 0

    if (
        intent.brand_preference == "PREFERRED"
        and intent.brand is not None
        and product.brand.casefold() == intent.brand.casefold()
    ):
        brand_score = 12

    if (
        intent.color_preference == "PREFERRED"
        and intent.color is not None
        and product.color is not None
        and product.color.casefold() == intent.color.casefold()
    ):
        color_score = 8

    return brand_score + color_score, brand_score, color_score


def rank_products(
    intent: IntentMandate,
    products: list[Product]
):
    if not products:
        return []

    ranked_results = []

    for product in products:

        feature_match_count, matched_features = calculate_feature_match(
            intent.preferred_features,
            product
        )

        preference_score, brand_score, color_score = calculate_preference_score(
            intent,
            product,
        )

        # -----------------------------
        # Rating score: max 40
        # -----------------------------
        rating_score = (
            product.rating / 5
        ) * 40

        # -----------------------------
        # Feature score: max 40
        # -----------------------------
        if intent.preferred_features:
            feature_score = (
                feature_match_count
                / len(intent.preferred_features)
            ) * 40
        else:
            feature_score = 0

        # -----------------------------
        # Price score: max 20
        # Cheaper valid products score higher
        # -----------------------------
        proposed_total = product.price * intent.quantity
        price_score = (
            1 - (proposed_total / intent.max_budget)
        ) * 20

        price_score = max(price_score, 0)

        # -----------------------------
        # Final score
        # -----------------------------
        if intent.priority == "BEST_VALUE":

            total_score = (
                rating_score
                + feature_score
                + price_score
                + preference_score
            )

        elif intent.priority == "CHEAPEST":

            total_score = (
                rating_score * 0.2
                + feature_score * 0.2
                + price_score * 3
                + preference_score
            )

        elif intent.priority == "HIGHEST_RATING":

            total_score = (
                rating_score * 1.5
                + feature_score
                + price_score * 0.5
                + preference_score
            )

        else:

            total_score = (
                rating_score
                + feature_score
                + price_score
                + preference_score
            )

        ranked_results.append({
            "product": product,

            "score": round(total_score, 2),

            "matched_features": matched_features,

            "score_breakdown": {
                "rating_score": round(rating_score, 2),
                "feature_score": round(feature_score, 2),
                "price_score": round(price_score, 2),
                "preference_score": preference_score,
                "brand_preference_score": brand_score,
                "color_preference_score": color_score,
            },

            "explanation": {
                "rating": product.rating,
                "preferred_features_matched": feature_match_count,
                "preferred_features_requested": len(
                    intent.preferred_features
                ),
                "unit_price": product.price,
                "proposed_total": proposed_total,
                "budget": intent.max_budget
            }
        })

    ranked_results.sort(
        key=lambda result: result["score"],
        reverse=True
    )

    return ranked_results
