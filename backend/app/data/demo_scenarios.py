from backend.app.schemas.demo import DemoScenario


demo_scenarios = [
    DemoScenario(
        scenario_id="normal-purchase",
        title="Normal authorized purchase",
        purpose=(
            "Show an explicit selection passing recommendation integrity, "
            "the Trust Gate, idempotent payment creation, and a webhook."
        ),
        expected_outcome="CAPTURED",
        api_story=[
            "Persist an intent",
            "Confirm PROD-001",
            "Run the deterministic orchestration pipeline",
            "Create one internal simulated payment",
            "Apply a CAPTURED webhook",
        ],
    ),
    DemoScenario(
        scenario_id="meaningful-tradeoff",
        title="Meaningful price-value trade-off",
        purpose=(
            "Show that the ₹4,800 recommendation cannot silently replace "
            "the ₹3,200 option without user selection."
        ),
        expected_outcome="REASK",
        api_story=[
            "Persist a non-autonomous ₹5,000 intent",
            "Rank Sony products",
            "Surface both valid options",
            "Stop for user confirmation",
        ],
    ),
    DemoScenario(
        scenario_id="budget-stretch",
        title="Above-budget recommendation boundary",
        purpose=(
            "Show PROD-004 as a useful ₹500 stretch candidate while keeping "
            "it out of the executable proposal."
        ),
        expected_outcome="REASK",
        api_story=[
            "Persist a ₹5,000 intent",
            "Identify the ₹5,500 stretch candidate",
            "Return REASK",
            "Do not create a payment",
        ],
    ),
    DemoScenario(
        scenario_id="unauthorized-subscription",
        title="Unauthorized subscription tampering",
        purpose=(
            "Show final transaction verification blocking a subscription "
            "that the mandate did not authorize."
        ),
        expected_outcome="BLOCK",
        api_story=[
            "Persist an intent with subscription_allowed=false",
            "Submit a tampered subscription proposal",
            "Run deterministic verification",
            "Block before payment",
        ],
    ),
    DemoScenario(
        scenario_id="timeout-and-duplicate",
        title="Timeout uncertainty and duplicate protection",
        purpose=(
            "Show one logical payment surviving a replay, entering UNKNOWN, "
            "and reconciling through one idempotent webhook."
        ),
        expected_outcome="CAPTURED_WITH_DUPLICATES_PREVENTED",
        api_story=[
            "Create a payment with an idempotency key",
            "Replay the same logical request",
            "Move PENDING to UNKNOWN after simulated timeout",
            "Reconcile CAPTURED from a webhook",
            "Ignore the duplicate webhook event",
        ],
    ),
]


demo_scenarios_by_id = {
    scenario.scenario_id: scenario
    for scenario in demo_scenarios
}

