from backend.app.data.evaluation_cases import evaluation_cases
from backend.app.services.evaluation_service import run_evaluation_suite


def test_synthetic_dataset_contains_500_unique_cases():
    assert len(evaluation_cases) == 500
    assert len({case.case_id for case in evaluation_cases}) == 500
    assert len({case.intent.max_budget for case in evaluation_cases}) > 100


def test_complete_evaluation_suite_matches_expected_baseline():
    report = run_evaluation_suite()
    metrics = report.metrics

    assert metrics.total_cases == 500
    assert metrics.passed_cases == 500
    assert metrics.pass_rate_percent == 100
    assert metrics.decision_accuracy_percent == 100
    assert metrics.reason_code_accuracy_percent == 100
    assert metrics.product_accuracy_percent == 100
    assert metrics.unsafe_allow_count == 0
    assert metrics.false_block_count == 0
    assert metrics.outcome_counts == {
        "ALLOW": 150,
        "REASK": 150,
        "BLOCK": 125,
        "ESCALATE": 75,
    }
    assert report.case_results == []


def test_evaluation_api_returns_measured_metrics(client):
    response = client.post("/evaluations/run")

    assert response.status_code == 200
    body = response.json()
    assert body["synthetic_data_only"] is True
    assert body["metrics"]["total_cases"] == 500
    assert body["metrics"]["passed_cases"] == 500
    assert body["metrics"]["average_decision_latency_ms"] >= 0
    assert body["metrics"]["p95_decision_latency_ms"] >= 0
    assert body["case_results"] == []


def test_evaluation_dataset_api_is_bounded(client):
    response = client.get("/evaluations/cases?limit=3")

    assert response.status_code == 200
    body = response.json()
    assert body["total_cases"] == 500
    assert body["returned_cases"] == 3
    assert len(body["cases"]) == 3

    invalid = client.get("/evaluations/cases?limit=501")
    assert invalid.status_code == 422

