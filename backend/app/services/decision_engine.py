from backend.app.schemas.decision import DecisionType

BLOCK_CODES = {
    "PRODUCT_NOT_FOUND",
    "CATEGORY_MISMATCH",
    "BRAND_MISMATCH",
    "COLOR_MISMATCH",
    "UNIT_PRICE_MISMATCH",
    "TOTAL_AMOUNT_MISMATCH",
    "UNAUTHORIZED_SUBSCRIPTION",
}

REASK_CODES = {
    "BUDGET_EXCEEDED",
    "QUANTITY_MISMATCH",
    "OUT_OF_STOCK",
    "PRODUCT_SELECTION_NOT_CONFIRMED",
    "PRODUCT_SELECTION_MISMATCH",
}

ESCALATE_CODES = set()

def make_decision(
        verification_result: dict
):
    if verification_result["verified"]:
        return {
            "decision": DecisionType.ALLOW,
            "reason_code": "INTENT_VERIFIED",
            "message": (
                "The proposed purchase matches "
                "the user's current authorization."
            )
        }

    violations = verification_result.get(
        "violations",
        []
    )

    violation_codes = {
        violation["code"]
        for violation in violations
    }

    # --------------------------------
    # Highest priority: BLOCK
    # --------------------------------

    if violation_codes & BLOCK_CODES:
        return {
            "decision": DecisionType.BLOCK,
            "reason_code": "HARD_CONSTRAINT_VIOLATION",
            "message": (
                "The proposed purchase violates "
                "a hard authorization or transaction-integrity rule."
            ),
            "violations": violations
        }
    # --------------------------------
    # Human review
    # --------------------------------
    if violation_codes & ESCALATE_CODES:
        return {
            "decision": DecisionType.ESCALATE,
            "reason_code": "HUMAN_REVIEW_REQUIRED",
            "message": (
                "The purchasse requires human review."
            ),
            "violations": violations
        }
    # --------------------------------
    # User must authorize/change something
    # --------------------------------
    if violation_codes & REASK_CODES:
        return {
            "decision": DecisionType.REASK,
            "reason_code": "USER_REAUTHORIZATION_REQUIRED",
            "message": (
                "The purchase cannot continue without "
                "additional user authorization or a new choice."
            ),
            "violations": violations
        }
    # --------------------------------
    # Fail closed for unknown violations
    # --------------------------------
    return {
        "decision": DecisionType.BLOCK,
        "reason_code": "UNKNOWN_VERIFICATION_FAILURE",
        "message": (
            "The purchase was blocked because "
            "the verification failure is not recognized."
        ),
        "violations": violations
    }
