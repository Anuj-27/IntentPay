from backend.app.schemas.merchant_policy import MerchantPolicy


def evaluate_merchant_policy(
    verification_result: dict,
    policy: MerchantPolicy,
    merchant_access_result: dict | None = None,
    autonomous_usage_today: tuple[int, int] = (0, 0),
):
    """Is this transaction safe and authorized for autonomous execution?

    Not "is this above a small fixed amount" -- at real volume a human
    cannot approve every transaction over a fixed rupee number. Anything
    within the merchant's autonomous envelope (per-transaction limit AND
    daily aggregate caps) auto-approves; anything outside it is an
    exception, and `policy.require_human_review_for_policy_exceptions`
    decides whether that exception goes to a human review queue
    (REVIEW_REQUIRED -> Trust Gate ESCALATE) or is hard-rejected instead
    (REJECTED -> Trust Gate BLOCK). Stays a pure function: the caller
    supplies today's usage as a plain tuple (see merchant_usage_service.
    get_today_usage) rather than this function touching a db session
    itself, so it's unit-testable exactly like before.

    `policy.require_human_review_for_high_risk` is intentionally NOT
    evaluated here. There is no risk-scoring signal anywhere in this
    codebase today, and merchant policy must stay independent and
    deterministic -- it does not read Intent/Trust-layer events like a
    budget-stretch reauthorization. The field is stored and validated as
    a reserved extension point for a future real risk engine rather than
    faked with an invented heuristic.
    """

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

    # --------------------------------
    # Absolute hard ceiling -- a fraud/liability cap, never processed by
    # this system at all, reviewed or not.
    # --------------------------------
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

    exception_status = "REVIEW_REQUIRED" if policy.require_human_review_for_policy_exceptions else "REJECTED"
    requires_human_approval = policy.require_human_review_for_policy_exceptions

    # --------------------------------
    # Daily aggregate caps -- the scale-safety valve. Once a merchant's
    # autonomous budget for today is used up, further transactions are an
    # exception even if each one is individually small.
    # --------------------------------
    amount_used_today, count_used_today = autonomous_usage_today

    if (
        policy.daily_autonomous_amount_limit is not None
        and amount_used_today + expected_total > policy.daily_autonomous_amount_limit
    ):
        return {
            "status": exception_status,
            "requires_human_approval": requires_human_approval,
            "reason_code": "DAILY_AUTONOMOUS_LIMIT_EXCEEDED",
            "threshold": policy.daily_autonomous_amount_limit,
            "amount": amount_used_today + expected_total,
            "message": (
                f"Today's autonomous total would reach "
                f"₹{amount_used_today + expected_total}, exceeding the "
                f"merchant's daily autonomous amount limit of "
                f"₹{policy.daily_autonomous_amount_limit}."
            ),
        }

    if (
        policy.daily_autonomous_transaction_limit is not None
        and count_used_today + 1 > policy.daily_autonomous_transaction_limit
    ):
        return {
            "status": exception_status,
            "requires_human_approval": requires_human_approval,
            "reason_code": "DAILY_AUTONOMOUS_LIMIT_EXCEEDED",
            "threshold": policy.daily_autonomous_transaction_limit,
            "amount": count_used_today + 1,
            "message": (
                f"This would be autonomous transaction "
                f"#{count_used_today + 1} today, exceeding the "
                f"merchant's daily autonomous transaction limit of "
                f"{policy.daily_autonomous_transaction_limit}."
            ),
        }

    # --------------------------------
    # Optional stricter bar within the autonomous envelope.
    # --------------------------------
    if (
        policy.high_value_review_threshold is not None
        and expected_total > policy.high_value_review_threshold
    ):
        return {
            "status": exception_status,
            "requires_human_approval": requires_human_approval,
            "reason_code": "HIGH_VALUE_REVIEW_REQUIRED",
            "threshold": policy.high_value_review_threshold,
            "amount": expected_total,
            "message": (
                f"Purchase amount ₹{expected_total} exceeds "
                f"the merchant's high-value review threshold "
                f"₹{policy.high_value_review_threshold}."
            ),
        }

    # --------------------------------
    # The autonomous-execution envelope itself.
    # --------------------------------
    if (
        policy.autonomous_transaction_limit is not None
        and expected_total > policy.autonomous_transaction_limit
    ):
        return {
            "status": exception_status,
            "requires_human_approval": requires_human_approval,
            "reason_code": "AUTONOMOUS_LIMIT_EXCEEDED",
            "threshold": policy.autonomous_transaction_limit,
            "amount": expected_total,
            "message": (
                f"Purchase amount ₹{expected_total} exceeds "
                f"merchant autonomous-execution limit "
                f"₹{policy.autonomous_transaction_limit}."
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
