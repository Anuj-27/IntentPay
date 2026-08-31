# IntentPay

IntentPay is an AI-native commerce orchestration and trust layer for safe,
explainable agent-assisted purchasing.

## Core safety rules

- Persisted intent mandates are the source of payment authorization.
- A caller cannot replace an intent while creating a payment.
- Non-autonomous product selection requires a separate user-confirmation step.
- Budgets apply to the complete quantity-aware purchase total.
- Deterministic verification and merchant policy checks gate every payment record.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env`, then apply the database migrations and start the API:

```powershell
python -m alembic upgrade head
python -m uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

## Test

```powershell
python -m pytest -q
```

The tests use an in-memory SQLite database and do not call OpenAI or the
configured PostgreSQL database.

## Evaluation and demo

IntentPay includes a versioned 500-case synthetic safety benchmark and five
reproducible local demo scenarios:

```powershell
# Start the API first, then run all scenarios and the benchmark.
.\scripts\run_demo.ps1 -IncludeBenchmark
```

The demo uses `INTERNAL_LEDGER_SIMULATION`; it never moves real money and does
not claim to be Razorpay Test Mode. See `docs/IntentPay_5_Minute_Demo.md` for the
timed recording script.

## Razorpay Test Mode

The provider adapter accepts only `rzp_test_` keys. Configure these values in
`.env` when you are ready to use your own Razorpay Test Mode account:

```text
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
```

Check readiness without exposing secrets:

```text
GET /payments/razorpay-test/configuration
```

The integration includes order creation, deterministic response verification,
server-side Checkout signature verification, raw-body webhook HMAC validation,
event replay protection, timeout recovery by receipt, and provider-state
reconciliation. See `docs/Razorpay_Test_Mode_Setup.md` for the complete flow.

## Safe purchase flow

1. `POST /intents/parse` or `POST /intents/parse/llm` to extract an intent.
2. `POST /intents` to persist the approved mandate.
3. `POST /products/filter` to compare valid products.
4. If autonomous selection is disabled, call
   `POST /intents/{intent_id}/selection` after the user chooses a product.
5. `POST /verify-purchase` with the persisted `intent_id`.
6. `POST /payments/create` with the same `intent_id` and an idempotency key.

For a typed preview of stages 3–5, call
`POST /intents/{intent_id}/orchestrate`. It returns the full decision trace and
next action without executing a payment.

The LLM endpoint uses OpenAI Structured Outputs with the model configured by
`OPENAI_INTENT_MODEL`. The deterministic endpoint remains available for local
development without API usage.
