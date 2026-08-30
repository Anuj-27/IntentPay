from backend.app.schemas.merchant_policy import MerchantPolicy

def evaluate_merchant_policy(
        verification_reasult: dict,
        policy: MerchantPolicy
):
    # --------------------------------
    # Do not evaluate merchant policy
    # if user-intent verification failed
    # --------------------------------
    if not verification_reasult["verified"]:
            return {
                "status": "NOT_EVALUATED",
                "requires_human_approval": False,
                "reason_code": "INTENT_VERIFICATION_FAILED",
                "message": (
                    "Merchant policy was not evaluated bacause "
                    "the purchase failed intent verification."
                )
            }
    expected_total = verification_reasult[
         "expected_total"
    ]

    if (
        policy.human_approval_threshold is not None and expected_total > policy.human_approval_threshold
    ):
        return{
            "status": "REVIEW_REQUIRED",
            "requires_human_approval": True,
            "reason_code": "MERCHANT_APPROVAL_THRESHOLD",
            "threshold": policy.human_approval_threshold,
            "amount": expected_total,
            "message": (
                f"purchase amount ₹{expected_total} exceeds "
                f"merchant auto-approval threshold "
                f"₹{policy.human_approval_threshold}."
            )
        }
    return {
        "status": "APPROVED",
        "requires_human_approval": False,
        "reason_code": "MERCHANT_POLICY_PASSED",
        "message": (
            "The purchase satisfies the merchant's "
            "automatic approval policy."
        )
    }
