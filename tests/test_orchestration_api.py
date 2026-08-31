BASE_INTENT = {
    "product_category": "headphones",
    "max_budget": 5000,
    "brand": "Sony",
    "brand_preference": "EXACT",
    "autonomous_selection_allowed": False,
    "preferred_features": ["ANC", "fast charging"],
}


def test_orchestration_exposes_complete_payment_ready_trace(client):
    intent_id = client.post("/intents", json=BASE_INTENT).json()["intent_id"]
    client.post(
        f"/intents/{intent_id}/selection",
        json={"product_id": "PROD-001"},
    )

    response = client.post(f"/intents/{intent_id}/orchestrate")

    assert response.status_code == 200
    body = response.json()
    assert body["protocol_context"]["intent_id"] == intent_id
    assert body["evaluation"]["recommendation_integrity"]["verified"] is True
    assert body["evaluation"]["final_decision"]["decision"] == "ALLOW"
    assert body["evaluation"]["ready_for_payment"] is True
    assert body["next_action"] == "SUBMIT_IDEMPOTENT_PAYMENT_COMMAND"
    assert body["payment_executed"] is False
    assert body["stage_trace"][-1] == {
        "stage": "PAYMENT_BOUNDARY",
        "status": "READY",
        "reason_code": "READY_FOR_IDEMPOTENT_PAYMENT",
    }


def test_orchestration_stops_for_a_meaningful_tradeoff(client):
    intent_id = client.post("/intents", json=BASE_INTENT).json()["intent_id"]

    response = client.post(f"/intents/{intent_id}/orchestrate")

    assert response.status_code == 200
    body = response.json()
    assert body["evaluation"]["final_decision"]["decision"] == "REASK"
    assert (
        body["evaluation"]["final_decision"]["reason_code"]
        == "MEANINGFUL_PRICE_VALUE_TRADEOFF"
    )
    assert (
        body["next_action"]
        == "REQUEST_USER_CONFIRMATION_OR_REAUTHORIZATION"
    )
    assert body["stage_trace"][-1]["status"] == "NOT_RUN"


def test_orchestration_route_is_typed_in_openapi(client):
    operation = client.get("/openapi.json").json()["paths"][
        "/intents/{intent_id}/orchestrate"
    ]["post"]

    response_schema = operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"].endswith("EndToEndOrchestrationResult")

