from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.purchase import ProposedPurchase
from backend.app.schemas.product import Product


def verify_purchase(
    intent: IntentMandate,
    purchase: ProposedPurchase,
    products: list[Product],
    selected_product_id: str | None = None,
):
    violations = []

    # --------------------------------
    # Find canonical product
    # --------------------------------
    catalog_product = next(
        (
            product
            for product in products
            if product.product_id == purchase.product_id
        ),
        None
    )

    # --------------------------------
    # Product must exist
    # --------------------------------
    if catalog_product is None:
        return {
            "verified": False,
            "expected_total": None,
            "violations": [
                {
                    "code": "PRODUCT_NOT_FOUND",
                    "message": (
                        f"Product '{purchase.product_id}' "
                        f"does not exist in the merchant catalog."
                    )
                }
            ]
        }

    # --------------------------------
    # Verify product category
    # --------------------------------
    if catalog_product.category.casefold() != intent.product_category.casefold():
        violations.append({
            "code": "CATEGORY_MISMATCH",
            "message": (
                f"User requested category "
                f"'{intent.product_category}', "
                f"but proposed product category is "
                f"'{catalog_product.category}'."
            )
        })

    # --------------------------------
    # Verify stock
    # --------------------------------
    if not catalog_product.in_stock:
        violations.append({
            "code": "OUT_OF_STOCK",
            "message": (
                f"Product '{catalog_product.product_id}' "
                f"is currently out of stock."
            )
        })


    # --------------------------------
    # Verify exact brand constraint
    # --------------------------------
    if (
        intent.brand_preference == "EXACT"
        and catalog_product.brand.casefold() != intent.brand.casefold()
    ):
        violations.append({
            "code": "BRAND_MISMATCH",
            "message": (
                f"User authorized brand '{intent.brand}', "
                f"but proposed product brand is "
                f"'{catalog_product.brand}'."
            )
        })

    # --------------------------------
    # Verify exact color constraint
    # --------------------------------
    if (
        intent.color_preference == "EXACT"
        and (
            catalog_product.color is None
            or catalog_product.color.casefold() != intent.color.casefold()
        )
    ):
        violations.append({
            "code": "COLOR_MISMATCH",
            "message": (
                f"User authorized color '{intent.color}', "
                f"but proposed product color is "
                f"'{catalog_product.color}'."
            )
        })

    # --------------------------------
    # Merchant catalog is source of truth
    # --------------------------------
    canonical_unit_price = catalog_product.price

    expected_total = (
        canonical_unit_price * purchase.quantity
    )

    # --------------------------------
    # 1. Verify proposed unit price
    # --------------------------------
    if purchase.unit_price != canonical_unit_price:
        violations.append({
            "code": "UNIT_PRICE_MISMATCH",
            "message": (
                f"Proposed unit price ₹{purchase.unit_price} "
                f"does not match catalog price "
                f"₹{canonical_unit_price}."
            )
        })

    # --------------------------------
    # 2. Verify total amount
    # --------------------------------
    if purchase.total_amount != expected_total:
        violations.append({
            "code": "TOTAL_AMOUNT_MISMATCH",
            "message": (
                f"Expected total is ₹{expected_total} "
                f"but proposed total is "
                f"₹{purchase.total_amount}."
            )
        })

    # --------------------------------
    # 3. Verify quantity
    # --------------------------------
    if purchase.quantity != intent.quantity:
        violations.append({
            "code": "QUANTITY_MISMATCH",
            "message": (
                f"User authorized quantity {intent.quantity}, "
                f"but proposed quantity is "
                f"{purchase.quantity}."
            )
        })

    # --------------------------------
    # 4. Verify budget
    # --------------------------------
    if expected_total > intent.max_budget:
        violations.append({
            "code": "BUDGET_EXCEEDED",
            "message": (
                f"Calculated total ₹{expected_total} exceeds "
                f"authorized budget ₹{intent.max_budget}."
            )
        })

    # --------------------------------
    # 5. Verify subscription
    # --------------------------------
    if (
        purchase.subscription
        and not intent.subscription_allowed
    ):
        violations.append({
            "code": "UNAUTHORIZED_SUBSCRIPTION",
            "message": (
                "The proposed purchase contains a subscription "
                "that the user did not authorize."
            )
        })

    # --------------------------------
    # 6. Verify user product selection
    # --------------------------------
    if not intent.autonomous_selection_allowed:
        if selected_product_id is None:
            violations.append({
                "code": "PRODUCT_SELECTION_NOT_CONFIRMED",
                "message": (
                    "The user has not confirmed a final product "
                    "and autonomous selection is not authorized."
                ),
            })
        elif selected_product_id != purchase.product_id:
            violations.append({
                "code": "PRODUCT_SELECTION_MISMATCH",
                "message": (
                    f"The user confirmed product '{selected_product_id}', "
                    f"but the proposed product is '{purchase.product_id}'."
                ),
            })

    if violations:
        return {
            "verified": False,
            "catalog_unit_price": canonical_unit_price,
            "expected_total": expected_total,
            "violations": violations
        }

    return {
        "verified": True,
        "catalog_unit_price": canonical_unit_price,
        "expected_total": expected_total,
        "violations": []
    }
