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

## Safe purchase flow

1. `POST /intents/parse` or `POST /intents/parse/llm` to extract an intent.
2. `POST /intents` to persist the approved mandate.
3. `POST /products/filter` to compare valid products.
4. If autonomous selection is disabled, call
   `POST /intents/{intent_id}/selection` after the user chooses a product.
5. `POST /verify-purchase` with the persisted `intent_id`.
6. `POST /payments/create` with the same `intent_id` and an idempotency key.

The LLM endpoint uses OpenAI Structured Outputs with the model configured by
`OPENAI_INTENT_MODEL`. The deterministic endpoint remains available for local
development without API usage.
