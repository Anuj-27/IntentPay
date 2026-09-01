from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.product import Product


def _attribute_values_match(expected, actual) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().casefold() == actual.strip().casefold()
    return expected == actual


def filter_products(
    intent: IntentMandate,
    products: list[Product]
):

    allowed_products = []
    rejected_products = []

    for product in products:
        reasons = []
        proposed_total = product.price * intent.quantity

        if product.category.casefold() != intent.product_category.casefold():
            reasons.append({
                "code": "CATEGORY_MISMATCH",
                "message": (
                    f"Product category '{product.category}' does not match "
                    f"requested category '{intent.product_category}'."
                )
            })

        if proposed_total > intent.max_budget:
            reasons.append({
            "code": "BUDGET_EXCEEDED",
            "message": (
                f"Purchase total ₹{proposed_total} "
                f"({intent.quantity} × ₹{product.price}) exceeds "
                f"budget ₹{intent.max_budget}."
            )
        })

        if not product.in_stock:
            reasons.append({
                "code": "OUT_OF_STOCK",
                "message": "Product is currently out of stock."
            })

        if (
            intent.brand_preference == "EXACT"
            and product.brand.casefold() != intent.brand.casefold()
        ):
            reasons.append({
                "code": "BRAND_MISMATCH",
                "message": (
                    f"User requires brand '{intent.brand}', "
                    f"but product brand is '{product.brand}'."
                )
            })

        for attribute_name, required_value in intent.required_attributes.items():
            product_value = product.attributes.get(attribute_name)
            if product_value is None or not _attribute_values_match(
                required_value,
                product_value,
            ):
                reasons.append({
                    "code": "ATTRIBUTE_MISMATCH",
                    "message": (
                        f"Product attribute '{attribute_name}' is "
                        f"'{product_value}', but the intent requires "
                        f"'{required_value}'."
                    ),
                })

        if (
            intent.color_preference == "EXACT"
            and (
                product.color is None
                or product.color.casefold() != intent.color.casefold()
            )
        ):
            reasons.append({
                "code": "COLOR_MISMATCH",
                "message": (
                    f"User requires color '{intent.color}', "
                    f"but product color is '{product.color}'."
                )
            })

        if reasons:
            rejected_products.append({
                "product": product,
                "reasons": reasons
            })
        else:
            allowed_products.append(product)

    return allowed_products,  rejected_products
