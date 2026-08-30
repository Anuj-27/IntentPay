from backend.app.schemas.decision import DecisionType

def evaluate_trust_gate(
        intent_decision: dict,
        merchant_policy_result: dict
):
    intent_result = intent_decision["decision"]

    # --------------------------------
    # User authorization failed
    # --------------------------------
    if intent_result == DecisionType.BLOCK:
        return{
            "decision": DecisionType.BLOCK,
            "reason_code": intent_decision["reason_code"],
            "message": intent_decision["message"]
        }

    if intent_result == DecisionType.REASK:
        return {
            "decision": DecisionType.REASK,
            "reason_code": intent_decision["reason_code"],
            "message": intent_decision["message"]
        }

    # --------------------------------
    # Merchant requires human approval
    # --------------------------------

    if merchant_policy_result.get(
        "requires_human_approval"
    ):
        return {
            "decision": DecisionType.ESCALATE,
            "reason_code": "MERCHANT_HUMAN_APPROVAL_REQUIRED",
            "message": (
                "The user authorized the purchase, "
                "but merchant policy requires human approval."
            )
        }

    # --------------------------------
    # Both user intent and merchant
    # policy are satisfied
    # --------------------------------
    if (
        intent_result == DecisionType.ALLOW and merchant_policy_result["status"] == "APPROVED"
    ):
        return {
            "decision": DecisionType.ALLOW,
            "reason_code": "TRUST_GATE_PASSED",
            "message": (
                "The purchase passed user authorization "
                "and merchant policy checks."
            )
        }
    # --------------------------------
    # Unknown state: fail closed
    # --------------------------------
    return{
        "decision": DecisionType.BLOCK,
        "reason_code": "TRUST_GATE_UNKNOWN_STATE",
        "message": (
            "The purchase was blocked because "
            "the trust state could not be determined."
        )
    }