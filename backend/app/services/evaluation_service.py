from math import ceil
from time import perf_counter_ns

from backend.app.data.evaluation_cases import (
    DATASET_NAME,
    DATASET_VERSION,
    evaluation_cases,
)
from backend.app.schemas.decision import DecisionType
from backend.app.schemas.evaluation import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationMetrics,
    EvaluationReport,
)
from backend.app.services.merchant_service import find_merchant_contract
from backend.app.services.orchestration_service import evaluate_intent_pipeline


def run_evaluation_case(case: EvaluationCase) -> EvaluationCaseResult:
    merchant_contract = find_merchant_contract(case.intent.merchant_id)

    if merchant_contract is None:
        raise ValueError(
            f"Evaluation merchant '{case.intent.merchant_id}' was not found."
        )

    started_at = perf_counter_ns()
    evaluation = evaluate_intent_pipeline(
        intent=case.intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=case.confirmed_product_id,
    )
    latency_ms = (perf_counter_ns() - started_at) / 1_000_000

    actual_product = (
        evaluation.buyer_agent.selected_product
        or evaluation.buyer_agent.recommended_product
    )
    actual_product_id = (
        actual_product.product_id
        if actual_product is not None
        else None
    )
    actual_decision = evaluation.final_decision.decision
    actual_reason_code = evaluation.final_decision.reason_code

    passed = (
        actual_decision == case.expected_decision
        and actual_reason_code == case.expected_reason_code
        and actual_product_id == case.expected_product_id
    )

    return EvaluationCaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=passed,
        expected_decision=case.expected_decision,
        actual_decision=actual_decision,
        expected_reason_code=case.expected_reason_code,
        actual_reason_code=actual_reason_code,
        expected_product_id=case.expected_product_id,
        actual_product_id=actual_product_id,
        latency_ms=round(latency_ms, 4),
    )


def percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def run_evaluation_suite(
    cases: list[EvaluationCase] | None = None,
    include_case_results: bool = False,
) -> EvaluationReport:
    selected_cases = cases if cases is not None else evaluation_cases
    results = [run_evaluation_case(case) for case in selected_cases]
    total = len(results)

    passed_cases = sum(result.passed for result in results)
    decision_matches = sum(
        result.actual_decision == result.expected_decision
        for result in results
    )
    reason_matches = sum(
        result.actual_reason_code == result.expected_reason_code
        for result in results
    )
    product_cases = [
        result
        for result in results
        if result.expected_product_id is not None
    ]
    product_matches = sum(
        result.actual_product_id == result.expected_product_id
        for result in product_cases
    )
    unsafe_allow_count = sum(
        result.actual_decision == DecisionType.ALLOW
        and result.expected_decision != DecisionType.ALLOW
        for result in results
    )
    false_block_count = sum(
        result.actual_decision == DecisionType.BLOCK
        and result.expected_decision != DecisionType.BLOCK
        for result in results
    )
    outcome_counts = {
        decision.value: sum(
            result.actual_decision == decision
            for result in results
        )
        for decision in DecisionType
    }
    latencies = sorted(result.latency_ms for result in results)
    average_latency = (
        sum(latencies) / total
        if total
        else 0.0
    )
    p95_latency = (
        latencies[max(ceil(total * 0.95) - 1, 0)]
        if latencies
        else 0.0
    )

    return EvaluationReport(
        dataset_name=DATASET_NAME,
        dataset_version=DATASET_VERSION,
        metrics=EvaluationMetrics(
            total_cases=total,
            passed_cases=passed_cases,
            pass_rate_percent=percentage(passed_cases, total),
            decision_accuracy_percent=percentage(decision_matches, total),
            reason_code_accuracy_percent=percentage(reason_matches, total),
            product_accuracy_percent=percentage(
                product_matches,
                len(product_cases),
            ),
            unsafe_allow_count=unsafe_allow_count,
            unsafe_allow_rate_percent=percentage(
                unsafe_allow_count,
                total,
            ),
            false_block_count=false_block_count,
            reauthorization_count=outcome_counts[DecisionType.REASK.value],
            policy_escalation_count=outcome_counts[DecisionType.ESCALATE.value],
            average_decision_latency_ms=round(average_latency, 4),
            p95_decision_latency_ms=round(p95_latency, 4),
            outcome_counts=outcome_counts,
        ),
        case_results=(results if include_case_results else []),
    )

