from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.product import Product


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
                    f"Product category '{product.category}' does not match"
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
