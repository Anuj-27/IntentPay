from backend.app.schemas.buyer_agent import BuyerAgentEvaluationResult
from backend.app.schemas.decision import DecisionType
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.merchant import MerchantContract
from backend.app.schemas.orchestration import FlowStage, FlowStageStatus
from backend.app.services.buyer_agent import run_buyer_agent
from backend.app.services.decision_engine import make_decision
from backend.app.services.intent_verifier import verify_purchase
from backend.app.services.merchant_policy_engine import evaluate_merchant_policy
from backend.app.services.merchant_service import check_merchant_access
from backend.app.services.safety_service import (
    evaluate_recommendation_integrity,
)
from backend.app.services.trust_gate import evaluate_trust_gate


def evaluate_intent_pipeline(
    intent: IntentMandate,
    merchant_contract: MerchantContract,
    confirmed_product_id: str | None = None,
) -> BuyerAgentEvaluationResult:
    buyer_result = run_buyer_agent(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
    )
    integrity_result = evaluate_recommendation_integrity(
        intent=intent,
        buyer_result=buyer_result,
        confirmed_product_id=confirmed_product_id,
    )

    if not integrity_result.verified:
        return BuyerAgentEvaluationResult(
            buyer_agent=buyer_result,
            recommendation_integrity=integrity_result,
            final_decision={
                "decision": DecisionType.BLOCK,
                "reason_code": "RECOMMENDATION_INTEGRITY_FAILED",
                "message": (
                    "The purchase flow was blocked because recommendation "
                    "integrity checks failed."
                ),
                "violations": [
                    violation.model_dump()
                    for violation in integrity_result.violations
                ],
            },
            ready_for_payment=False,
        )

    if buyer_result.proposed_purchase is None:
        return BuyerAgentEvaluationResult(
            buyer_agent=buyer_result,
            recommendation_integrity=integrity_result,
            final_decision={
                "decision": buyer_result.decision,
                "reason_code": buyer_result.reason_code,
                "message": buyer_result.message,
                "violations": [],
            },
            ready_for_payment=False,
        )

    merchant_access_result = check_merchant_access(
        merchant_contract,
        required_capabilities=("inventory_check", "checkout"),
    )
    verification_result = verify_purchase(
        intent,
        buyer_result.proposed_purchase,
        merchant_contract.catalog.products,
        selected_product_id=confirmed_product_id,
    )
    intent_decision = make_decision(verification_result)
    policy_result = evaluate_merchant_policy(
        verification_result,
        merchant_contract.merchant.policy,
        merchant_access_result=merchant_access_result,
    )
    final_decision = evaluate_trust_gate(
        intent_decision,
        policy_result,
    )

    return BuyerAgentEvaluationResult(
        buyer_agent=buyer_result,
        recommendation_integrity=integrity_result,
        verification=verification_result,
        intent_decision=intent_decision,
        merchant_policy=policy_result,
        final_decision=final_decision,
        ready_for_payment=(
            final_decision["decision"] == DecisionType.ALLOW
        ),
    )


def build_stage_trace(
    evaluation: BuyerAgentEvaluationResult,
) -> list[FlowStage]:
    trace = [
        FlowStage(
            stage="INTENT_MANDATE",
            status=FlowStageStatus.PASSED,
            reason_code="PERSISTED_INTENT_LOADED",
        ),
        FlowStage(
            stage="MERCHANT_CATALOG_AND_HARD_CONSTRAINTS",
            status=(
                FlowStageStatus.PASSED
                if evaluation.buyer_agent.ranked_products
                else FlowStageStatus.STOPPED
            ),
            reason_code=(
                "VALID_PRODUCTS_FOUND"
                if evaluation.buyer_agent.ranked_products
                else evaluation.buyer_agent.reason_code
            ),
        ),
        FlowStage(
            stage="PREFERENCE_TRADEOFF_AND_SELECTION",
            status=(
                FlowStageStatus.PASSED
                if evaluation.buyer_agent.proposed_purchase is not None
                else FlowStageStatus.STOPPED
            ),
            reason_code=evaluation.buyer_agent.reason_code,
        ),
        FlowStage(
            stage="RECOMMENDATION_INTEGRITY",
            status=(
                FlowStageStatus.PASSED
                if evaluation.recommendation_integrity.verified
                else FlowStageStatus.STOPPED
            ),
            reason_code=evaluation.recommendation_integrity.reason_code,
        ),
    ]

    for stage, value in (
        ("INTENT_VERIFIER", evaluation.intent_decision),
        ("MERCHANT_POLICY", evaluation.merchant_policy),
        ("TRUST_GATE", evaluation.final_decision),
    ):
        if value is None:
            trace.append(FlowStage(
                stage=stage,
                status=FlowStageStatus.NOT_RUN,
                reason_code="UPSTREAM_FLOW_STOPPED",
            ))
            continue

        reason_code = value.reason_code
        decision = getattr(value, "decision", None)
        policy_status = getattr(value, "status", None)
        passed = (
            decision == DecisionType.ALLOW
            or policy_status == "APPROVED"
        )

        trace.append(FlowStage(
            stage=stage,
            status=(
                FlowStageStatus.PASSED
                if passed
                else FlowStageStatus.STOPPED
            ),
            reason_code=reason_code,
        ))

    trace.append(FlowStage(
        stage="PAYMENT_BOUNDARY",
        status=(
            FlowStageStatus.READY
            if evaluation.ready_for_payment
            else FlowStageStatus.NOT_RUN
        ),
        reason_code=(
            "READY_FOR_IDEMPOTENT_PAYMENT"
            if evaluation.ready_for_payment
            else "TRUST_GATE_DID_NOT_ALLOW"
        ),
    ))

    return trace


def next_action_for_evaluation(
    evaluation: BuyerAgentEvaluationResult,
) -> str:
    decision = evaluation.final_decision.decision

    if decision == DecisionType.ALLOW:
        return "SUBMIT_IDEMPOTENT_PAYMENT_COMMAND"
    if decision == DecisionType.REASK:
        return "REQUEST_USER_CONFIRMATION_OR_REAUTHORIZATION"
    if decision == DecisionType.ESCALATE:
        return "REQUEST_MERCHANT_HUMAN_APPROVAL"
    return "STOP_PURCHASE"

