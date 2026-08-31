from time import perf_counter_ns
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.data.demo_scenarios import demo_scenarios_by_id
from backend.app.schemas.decision import DecisionType
from backend.app.schemas.demo import DemoScenarioRun
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.payment import PaymentStatus
from backend.app.schemas.purchase import ProposedPurchase
from backend.app.services.decision_engine import make_decision
from backend.app.services.intent_service import (
    confirm_product_selection,
    create_intent_record,
)
from backend.app.services.intent_verifier import verify_purchase
from backend.app.services.merchant_policy_engine import evaluate_merchant_policy
from backend.app.services.merchant_service import (
    check_merchant_access,
    find_merchant_contract,
)
from backend.app.services.orchestration_service import (
    build_stage_trace,
    evaluate_intent_pipeline,
)
from backend.app.services.payment_service import (
    create_payment,
    update_payment_status,
)
from backend.app.services.trust_gate import evaluate_trust_gate
from backend.app.services.webhook_service import process_payment_webhook


DEMO_MODE = "INTERNAL_LEDGER_SIMULATION"


def demo_intent(
    *,
    max_budget: int = 5000,
    autonomous: bool = False,
) -> IntentMandate:
    return IntentMandate(
        product_category="headphones",
        max_budget=max_budget,
        brand="Sony",
        brand_preference="EXACT",
        subscription_allowed=False,
        autonomous_selection_allowed=autonomous,
        preferred_features=["ANC", "fast charging"],
    )


def persist_demo_intent(
    db: Session,
    intent: IntentMandate,
    selected_product_id: str | None = None,
):
    intent_record = create_intent_record(db, intent)

    if selected_product_id is not None:
        intent_record = confirm_product_selection(
            db,
            intent_record,
            selected_product_id,
        )

    return intent_record


def demo_contract(intent: IntentMandate):
    merchant_contract = find_merchant_contract(intent.merchant_id)
    if merchant_contract is None:
        raise ValueError("The demo merchant contract is unavailable.")
    return merchant_contract


def run_pipeline_demo(
    db: Session,
    intent: IntentMandate,
    selected_product_id: str | None = None,
):
    intent_record = persist_demo_intent(
        db,
        intent,
        selected_product_id,
    )
    evaluation = evaluate_intent_pipeline(
        intent,
        demo_contract(intent),
        confirmed_product_id=selected_product_id,
    )
    return intent_record, evaluation


def execute_normal_purchase(db: Session) -> tuple[str, dict]:
    intent = demo_intent(max_budget=3500)
    intent_record, evaluation = run_pipeline_demo(
        db,
        intent,
        selected_product_id="PROD-001",
    )
    purchase = evaluation.buyer_agent.proposed_purchase
    if purchase is None or not evaluation.ready_for_payment:
        raise RuntimeError("The normal demo purchase did not pass the Trust Gate.")

    idempotency_key = f"demo-normal-{uuid4()}"
    payment_result = create_payment(
        db=db,
        intent_id=intent_record.intent_id,
        correlation_id=intent_record.correlation_id,
        protocol_version=intent_record.protocol_version,
        product_id=purchase.product_id,
        amount=purchase.total_amount,
        idempotency_key=idempotency_key,
    )
    payment_id = payment_result["payment"]["payment_id"]
    pending_result = update_payment_status(
        db,
        payment_id,
        PaymentStatus.PENDING,
    )
    webhook_result = process_payment_webhook(
        db=db,
        event_id=f"demo-event-{uuid4()}",
        payment_id=payment_id,
        new_status=PaymentStatus.CAPTURED,
    )

    return "CAPTURED", {
        "intent_id": intent_record.intent_id,
        "evaluation": evaluation.model_dump(mode="json"),
        "stage_trace": [
            stage.model_dump(mode="json")
            for stage in build_stage_trace(evaluation)
        ],
        "payment_created": payment_result["created"],
        "payment_id": payment_id,
        "payment_status_trace": [
            PaymentStatus.CREATED.value,
            pending_result["new_status"],
            webhook_result["result"]["new_status"],
        ],
        "provider": "INTERNAL_LEDGER",
    }


def execute_tradeoff(db: Session) -> tuple[str, dict]:
    intent_record, evaluation = run_pipeline_demo(
        db,
        demo_intent(),
    )
    return evaluation.final_decision.decision.value, {
        "intent_id": intent_record.intent_id,
        "evaluation": evaluation.model_dump(mode="json"),
        "stage_trace": [
            stage.model_dump(mode="json")
            for stage in build_stage_trace(evaluation)
        ],
        "payment_created": False,
    }


def execute_budget_stretch(db: Session) -> tuple[str, dict]:
    observed, result = execute_tradeoff(db)
    stretch_candidates = result["evaluation"]["buyer_agent"][
        "stretch_candidates"
    ]
    result["stretch_candidate_ids"] = [
        item["product"]["product_id"]
        for item in stretch_candidates
    ]
    result["above_budget_purchase_created"] = False
    return observed, result


def execute_subscription_attack(db: Session) -> tuple[str, dict]:
    intent = demo_intent(max_budget=3500, autonomous=True)
    intent_record = persist_demo_intent(db, intent)
    merchant_contract = demo_contract(intent)
    tampered_purchase = ProposedPurchase(
        product_id="PROD-001",
        quantity=1,
        unit_price=3200,
        total_amount=3200,
        subscription=True,
    )
    verification = verify_purchase(
        intent,
        tampered_purchase,
        merchant_contract.catalog.products,
    )
    intent_decision = make_decision(verification)
    policy_result = evaluate_merchant_policy(
        verification,
        merchant_contract.merchant.policy,
        merchant_access_result=check_merchant_access(
            merchant_contract,
            required_capabilities=("inventory_check", "checkout"),
        ),
    )
    final_decision = evaluate_trust_gate(intent_decision, policy_result)

    return DecisionType(final_decision["decision"]).value, {
        "intent_id": intent_record.intent_id,
        "tampered_purchase": tampered_purchase.model_dump(mode="json"),
        "verification": verification,
        "final_decision": {
            **final_decision,
            "decision": DecisionType(final_decision["decision"]).value,
        },
        "payment_created": False,
    }


def execute_timeout_and_duplicate(db: Session) -> tuple[str, dict]:
    intent = demo_intent(max_budget=3500)
    intent_record, evaluation = run_pipeline_demo(
        db,
        intent,
        selected_product_id="PROD-001",
    )
    purchase = evaluation.buyer_agent.proposed_purchase
    if purchase is None or not evaluation.ready_for_payment:
        raise RuntimeError("The timeout demo purchase did not pass the Trust Gate.")

    idempotency_key = f"demo-timeout-{uuid4()}"
    payment_arguments = {
        "db": db,
        "intent_id": intent_record.intent_id,
        "correlation_id": intent_record.correlation_id,
        "protocol_version": intent_record.protocol_version,
        "product_id": purchase.product_id,
        "amount": purchase.total_amount,
        "idempotency_key": idempotency_key,
    }
    first_result = create_payment(**payment_arguments)
    replay_result = create_payment(**payment_arguments)
    payment_id = first_result["payment"]["payment_id"]
    pending_result = update_payment_status(
        db,
        payment_id,
        PaymentStatus.PENDING,
    )
    unknown_result = update_payment_status(
        db,
        payment_id,
        PaymentStatus.UNKNOWN,
    )
    event_id = f"demo-timeout-event-{uuid4()}"
    webhook_result = process_payment_webhook(
        db,
        event_id,
        payment_id,
        PaymentStatus.CAPTURED,
    )
    duplicate_webhook = process_payment_webhook(
        db,
        event_id,
        payment_id,
        PaymentStatus.CAPTURED,
    )

    observed = "CAPTURED_WITH_DUPLICATES_PREVENTED"
    return observed, {
        "intent_id": intent_record.intent_id,
        "payment_id": payment_id,
        "payment_status_trace": [
            PaymentStatus.CREATED.value,
            pending_result["new_status"],
            unknown_result["new_status"],
            webhook_result["result"]["new_status"],
        ],
        "payment_replay_created": replay_result["created"],
        "payment_replay_reason": replay_result["reason_code"],
        "duplicate_webhook_processed": duplicate_webhook["processed"],
        "duplicate_webhook_reason": duplicate_webhook["reason_code"],
    }


DEMO_EXECUTORS = {
    "normal-purchase": execute_normal_purchase,
    "meaningful-tradeoff": execute_tradeoff,
    "budget-stretch": execute_budget_stretch,
    "unauthorized-subscription": execute_subscription_attack,
    "timeout-and-duplicate": execute_timeout_and_duplicate,
}


def run_demo_scenario(
    db: Session,
    scenario_id: str,
) -> DemoScenarioRun:
    scenario = demo_scenarios_by_id.get(scenario_id)
    executor = DEMO_EXECUTORS.get(scenario_id)

    if scenario is None or executor is None:
        raise ValueError(f"Demo scenario '{scenario_id}' was not found.")

    started_at = perf_counter_ns()
    observed_outcome, result = executor(db)
    duration_ms = (perf_counter_ns() - started_at) / 1_000_000

    return DemoScenarioRun(
        scenario_id=scenario_id,
        mode=DEMO_MODE,
        expected_outcome=scenario.expected_outcome,
        observed_outcome=observed_outcome,
        passed=observed_outcome == scenario.expected_outcome,
        duration_ms=round(duration_ms, 4),
        result=result,
    )

