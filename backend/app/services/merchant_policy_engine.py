from backend.app.schemas.merchant_policy import MerchantPolicy


def evaluate_merchant_policy(
    verification_result: dict,
    policy: MerchantPolicy,
    merchant_access_result: dict | None = None,
):
    # --------------------------------
    # Do not evaluate merchant policy
    # if user-intent verification failed
    # --------------------------------
    if not verification_result["verified"]:
        return {
            "status": "NOT_EVALUATED",
            "requires_human_approval": False,
            "reason_code": "INTENT_VERIFICATION_FAILED",
            "message": (
                "Merchant policy was not evaluated because "
                "the purchase failed intent verification."
            ),
        }

    expected_total = verification_result["expected_total"]

    if (
        merchant_access_result is not None
        and not merchant_access_result["available"]
    ):
        return {
            "status": "REJECTED",
            "requires_human_approval": False,
            "reason_code": merchant_access_result["reason_code"],
            "message": merchant_access_result["message"],
        }

    if (
        policy.max_transaction_amount is not None
        and expected_total > policy.max_transaction_amount
    ):
        return {
            "status": "REJECTED",
            "requires_human_approval": False,
            "reason_code": "MERCHANT_TRANSACTION_LIMIT_EXCEEDED",
            "threshold": policy.max_transaction_amount,
            "amount": expected_total,
            "message": (
                f"Purchase amount ₹{expected_total} exceeds "
                f"the merchant transaction limit "
                f"₹{policy.max_transaction_amount}."
            ),
        }

    if (
        policy.human_approval_threshold is not None
        and expected_total > policy.human_approval_threshold
    ):
        return {
            "status": "REVIEW_REQUIRED",
            "requires_human_approval": True,
            "reason_code": "MERCHANT_APPROVAL_THRESHOLD",
            "threshold": policy.human_approval_threshold,
            "amount": expected_total,
            "message": (
                f"Purchase amount ₹{expected_total} exceeds "
                f"merchant auto-approval threshold "
                f"₹{policy.human_approval_threshold}."
            ),
        }

    return {
        "status": "APPROVED",
        "requires_human_approval": False,
        "reason_code": "MERCHANT_POLICY_PASSED",
        "message": (
            "The purchase satisfies the merchant's "
            "automatic approval policy."
        ),
    }
