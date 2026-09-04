# IntentPay Five-Minute Demo

This script is designed for one continuous screen recording. It demonstrates
the implemented system honestly: payment examples use the internal ledger
simulator, no real money moves, and the credentialed provider option is limited
to the implemented Razorpay Test Mode boundary.

## Before recording

Run these checks from the project root:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000/` for the visual screenshot flow and keep
`http://127.0.0.1:8000/docs` available for deeper API evidence. Keep a second
terminal ready for:

```powershell
.\scripts\run_demo.ps1 -IncludeBenchmark
```

Expected preparation result: the full test suite passes, the API starts, and Swagger shows
the orchestration, safety, evaluation, demo, payment, webhook, and audit routes.

## 0:00–0:35 — The problem and one-line pitch

Say:

> AI can recommend a product, but recommendation is not payment authorization.
> IntentPay is a deterministic trust and orchestration layer that converts a
> user's intent into bounded, explainable permission before any agent-assisted
> purchase reaches a payment provider.

Show the project title and `GET /safety/manifest`.

## 0:35–1:10 — The architecture

Show `POST /intents/{intent_id}/orchestrate` in Swagger and say:

> The LLM may extract a structured intent, but it never makes the final money
> decision. The persisted mandate, merchant catalog, hard filters, ranking,
> recommendation-integrity guard, exact transaction verifier, merchant policy,
> and Trust Gate are separate deterministic stages. The result is only one of
> ALLOW, REASK, BLOCK, or ESCALATE.

Point out `payment_executed: false` in the orchestration schema. Explain that an
ALLOW is readiness, not an automatic charge.

If the response is `ESCALATE`, show that `next_action` is
`REQUEST_MERCHANT_HUMAN_APPROVAL`. The shopper can request review at
`POST /intents/{intent_id}/merchant-approval`; the merchant dashboard then
shows the exact product and amount. Approval re-runs the Trust Gate and only an
`ALLOW` exposes a payment request. A rejection becomes `BLOCK`.

Also briefly open `GET /categories` and `POST /visual-intents/analyze`:

> IntentPay is no longer tied to headphones. The demo registry covers five
> categories and three agent-readable merchants. A screenshot can identify a
> candidate, but the screenshot price is never spending permission. IntentPay
> verifies the catalog match and asks for exact product and budget confirmation
> before creating a mandate.

## 1:10–1:50 — Scenario 1: normal purchase

Run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo/scenarios/normal-purchase/run | ConvertTo-Json -Depth 12
```

Show `observed_outcome: CAPTURED`, `passed: true`,
`real_money_moved: false`, the Trust Gate ALLOW, and the status trace
`CREATED → PENDING → CAPTURED`.

Say:

> This uses the internal provider simulator. The same provider-neutral command
> boundary also supports the implemented Razorpay Test Mode adapter; I am not
> presenting a fake provider response as Razorpay.

## 1:50–2:35 — Scenario 2: meaningful trade-off

Run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo/scenarios/meaningful-tradeoff/run | ConvertTo-Json -Depth 12
```

Show the ₹3,200 and ₹4,800 Sony products, the recommended-price premium, and
`MEANINGFUL_PRICE_VALUE_TRADEOFF`.

Say:

> The ₹4,800 product ranks higher for ANC and fast charging, but it costs 50%
> more than the ₹3,200 valid option. Because autonomous selection was not
> granted, IntentPay returns REASK and creates no payment. User intent wins over
> conversion pressure.

## 2:35–3:20 — Scenarios 3 and 4: stretch and subscription

Run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo/scenarios/budget-stretch/run | ConvertTo-Json -Depth 12
Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo/scenarios/unauthorized-subscription/run | ConvertTo-Json -Depth 12
```

Say:

> A ₹5,500 product may be shown as a useful stretch above a ₹5,000 budget, but
> it cannot become an executable proposal without renewed authorization. In the
> next request, a subscription flag is added after intent creation. Final
> verification detects `UNAUTHORIZED_SUBSCRIPTION` and blocks before payment.

## 3:20–4:05 — Scenario 5: timeout and duplicate safety

Run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo/scenarios/timeout-and-duplicate/run | ConvertTo-Json -Depth 12
```

Show:

- `payment_replay_created: false`,
- `payment_replay_reason: IDEMPOTENT_REPLAY`,
- `CREATED → PENDING → UNKNOWN → CAPTURED`,
- `duplicate_webhook_processed: false`.

Say:

> A timeout is uncertainty, not proof of failure. IntentPay moves the payment to
> UNKNOWN, reconciles the later webhook, and prevents both a second logical
> payment and a repeated webhook effect.

## 4:05–4:40 — Real benchmark numbers

Run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/evaluations/run | ConvertTo-Json -Depth 8
```

Say:

> This is a versioned synthetic regression benchmark of 500 scenarios. The
> current baseline has 100% expected decision, reason-code, and product accuracy
> with zero unsafe ALLOWs. Latency is measured on this machine. These are not
> production-user or revenue claims; they prove repeatability over the declared
> test distribution.

## 4:40–5:00 — Close and roadmap

Say:

> IntentPay is not another shopping chatbot. It is a policy, authorization,
> value, and trust control plane for AI-native commerce. It supports typed
> multi-category catalogs, verified visual intents, and a Razorpay Test Mode
> boundary while preserving every deterministic gate shown here.

End on the project statement in `docs/IntentPay_Project_Context.md`.

## Optional credentialed Razorpay segment

After your own test keys and public webhook are configured, replace the internal
normal-purchase simulation with the home page's **Open Razorpay Checkout**
button. IntentPay creates the Test Mode order only after `ALLOW`, opens
Checkout using the returned options, verifies the browser signature, and can
then show the signed captured webhook. Keep the internal scenario as a
recording fallback.
Never place credentials or the full `.env` on screen.

## Recording fallback

If Swagger or the terminal output is too dense, run one scenario at a time and
collapse JSON fields that are not being discussed. Do not edit outcome values
for the recording. If a scenario fails, stop and rerun the automated tests
instead of presenting a stale screenshot.
