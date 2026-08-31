import pytest


EXPECTED_OUTCOMES = {
    "normal-purchase": "CAPTURED",
    "meaningful-tradeoff": "REASK",
    "budget-stretch": "REASK",
    "unauthorized-subscription": "BLOCK",
    "timeout-and-duplicate": "CAPTURED_WITH_DUPLICATES_PREVENTED",
}


def test_demo_catalog_lists_five_safe_scenarios(client):
    response = client.get("/demo/scenarios")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "INTERNAL_LEDGER_SIMULATION"
    assert body["real_money_moved"] is False
    assert {
        scenario["scenario_id"]
        for scenario in body["scenarios"]
    } == set(EXPECTED_OUTCOMES)


@pytest.mark.parametrize(
    ("scenario_id", "expected_outcome"),
    EXPECTED_OUTCOMES.items(),
)
def test_each_demo_scenario_reproduces_its_claimed_outcome(
    client,
    scenario_id,
    expected_outcome,
):
    response = client.post(f"/demo/scenarios/{scenario_id}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["expected_outcome"] == expected_outcome
    assert body["observed_outcome"] == expected_outcome
    assert body["passed"] is True
    assert body["real_money_moved"] is False

    if scenario_id == "budget-stretch":
        assert "PROD-004" in body["result"]["stretch_candidate_ids"]
        assert body["result"]["above_budget_purchase_created"] is False

    if scenario_id == "timeout-and-duplicate":
        assert body["result"]["payment_replay_created"] is False
        assert body["result"]["payment_replay_reason"] == "IDEMPOTENT_REPLAY"
        assert body["result"]["duplicate_webhook_processed"] is False
        assert (
            body["result"]["duplicate_webhook_reason"]
            == "DUPLICATE_WEBHOOK_EVENT"
        )


def test_unknown_demo_scenario_returns_structured_404(client):
    response = client.post("/demo/scenarios/not-real/run")

    assert response.status_code == 404
    assert response.json()["detail"]["reason_code"] == "DEMO_SCENARIO_NOT_FOUND"

