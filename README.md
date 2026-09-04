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

For any staging or production deployment, set `APP_ENV=production` and
replace the development `MERCHANT_SESSION_SECRET` with a unique random value
of at least 32 characters. The API now refuses to start in a secure
environment when that secret is missing or still set to the example value.
Set `APP_ORIGIN` to the public HTTPS origin as well; merchant catalog mutation
requests are rejected when their browser origin does not match it.

Open `http://127.0.0.1:8000/` for the text-first purchase workspace or
`http://127.0.0.1:8000/chat` for the full assistant conversation. The screenshot
is optional on the home page; it is an additional visual signal, not a required
input. Open `http://127.0.0.1:8000/docs` for interactive API documentation.

## Test

```powershell
python -m pytest -q
```

The tests use an in-memory SQLite database and do not call OpenAI or the
configured PostgreSQL database.

## Multi-category and visual intents

The demo merchant registry now covers headphones, smartphones, laptops,
smartwatches, and cameras across three mock merchant contracts. These are
clearly labelled demo catalogs under reserved `.example` domains; they do not
claim live inventory or an affiliation with the product brands.

Discover supported categories and merchant catalogs with:

```text
GET /categories
GET /merchants
GET /products?merchant_id=MERCHANT-002&category=smartphones
```

The screenshot workflow is deliberately split into discovery and financial
authorization:

1. `POST /visual-intents/analyze` reads a PNG, JPEG, or WebP screenshot using
   a local Ollama vision model by default and matches the extracted candidate
   against approved catalogs. If Ollama or its model is unavailable, the same
   request automatically falls back to free local Tesseract OCR plus the
   optional product hint. OpenAI Vision remains an optional mode.
2. A displayed screenshot price is never interpreted as a budget. Missing
   budgets return `MAX_BUDGET_REQUIRED`.
3. `POST /visual-intents/confirm` requires the exact merchant, product, maximum
   budget, quantity, and `confirmed: true` before persisting a mandate.
4. The confirmation response contains a `razorpay_test_request` only when the
   deterministic Buyer Agent, verifier, merchant policy, and Trust Gate return
   `ALLOW`.
5. Submit that object to `POST /payments/razorpay-test/orders`; the user still
   completes Razorpay Checkout and server-side verification.

Screenshots are size/type checked and processed without being persisted by the
visual-intent service. Both local analyzers keep screenshot bytes on the
machine. For image-only recognition, install Ollama and pull the small vision
model:

```powershell
winget install --id Ollama.Ollama --exact
ollama pull qwen2.5vl:3b
```

The API reports readiness at `GET /visual-intents/configuration`, including
`local_vision_gpu_accelerated` — `false` means Ollama is running the model on
CPU only, which is real but slow (multiple minutes per image on a typical
laptop); `null` means it can't currently be determined (e.g. the model isn't
loaded yet). Requests are allowed up to `LOCAL_VISION_TIMEOUT_SECONDS`
(default 240s) before falling back to OCR. If the model is not installed at
all, OCR fallback still works, but OCR reads only visible text — an isolated
product photo with no text on it needs the local vision model (or a typed
hint) to be identified. Install Tesseract on Windows with:

```powershell
winget install --id tesseract-ocr.tesseract --exact
```

Use a full product-page screenshot when possible. The local vision model can
also identify an isolated product photo; OCR fallback may correctly return
`VISUAL_CONFIDENCE_TOO_LOW` for an image without readable text unless a product
hint is entered. For much faster local vision inference, run Ollama on a
machine with a supported GPU; otherwise set `VISUAL_ANALYZER_MODE=OPENAI_VISION`
when paid OpenAI API access is available.

## Product assistant chat

Open `/chat` for the separate discovery surface. It accepts a conversation,
quick prompts, and drag-and-drop product images. `POST /assistant/chat` returns
catalog-grounded suggestions with merchant, price, score, reasons, and budget
fit. Chat is intentionally discovery-only: its “Open in Verify” action sends
the selected product to the existing screenshot verification page, where exact
product confirmation and the Trust Gate still happen.

The assistant uses local vision for attached images and deterministic catalog
retrieval for text preferences. This keeps recommendations explainable and
prevents a chat model from inventing products or authorizing a payment.

An explicit maximum is a hard ceiling for normal suggestions (`price ×
quantity <= max_budget`). Above-budget products are never included in that
approved set; when they provide meaningful additional value, they appear in a
separate `upsell_candidates` list with `status=REQUIRES_REAUTHORIZATION`.
Raising the maximum is a new explicit user decision and is revalidated by the
existing confirmation and Trust Gate flow.

## Merchant catalog management

Merchants log in at `/merchant` and manage their live catalog at
`/merchant/dashboard` — adding products, editing price/stock/features, and
deactivating listings. Changes are stored in the database and take effect
immediately on the buyer-facing catalog (`/products`, `/products/filter`,
and the full Trust Gate pipeline for that merchant ID), layered on top of
the static demo catalog rather than replacing it.

A new merchant can self-register from the same `/merchant` page ("New
merchant? Create an account") — pick a store name, a merchant ID, and a
password; the account starts with an empty catalog and appears in
`GET /merchants` and `GET /categories` as soon as it lists a product, so it
is discoverable through `/catalog` alongside the demo merchants. Known
boundary: self-registered merchants are reachable by direct ID everywhere
(their own dashboard, `/products?merchant_id=...`, the full purchase
pipeline) and appear in the merchant directory and category listings, but
are not yet included in the chat assistant's or visual-intent analyzer's
free-text/category discovery, which still search only the three built-in
demo merchants.

Demo credentials for the three built-in merchants (for evaluation only —
rotate `MERCHANT_SESSION_SECRET` and these passwords before any non-local
deployment):

```text
Merchant ID: MERCHANT-001, MERCHANT-002, or MERCHANT-003
Password:    IntentPayDemo!2026
```

Browse the catalog by category at `/catalog`, backed by the existing
`GET /categories` and `GET /products` endpoints.

### Merchant approval workflow

When an exact purchase is above the merchant's automatic approval threshold
but still below its hard transaction limit, the Trust Gate returns
`ESCALATE`. The shopper can request review with
`POST /intents/{intent_id}/merchant-approval`. An authenticated merchant can
review pending requests in the **Pending purchase approvals** section of
`/merchant/dashboard`, or use `GET /merchant/approvals` and
`POST /merchant/approvals/{approval_id}/decision` from Swagger. Approval is
bound to the original intent, product, and verified amount; IntentPay runs the
full Trust Gate again before returning `ALLOW`. A rejection becomes `BLOCK`,
and an expired request cannot create a payment order.

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
reconciliation. Once the Trust Gate returns `ALLOW`, the home page's
**Open Razorpay Checkout** button now loads Standard Checkout and posts its
response to the server for signature verification. See
`docs/Razorpay_Test_Mode_Setup.md` for the complete flow.

## Safe purchase flow

1. `POST /intents/parse`, `POST /intents/parse/llm`, or
   `POST /visual-intents/analyze` to extract an intent candidate.
2. `POST /intents` to persist the approved mandate.
3. `POST /products/filter` to compare valid products.
4. If autonomous selection is disabled, call
   `POST /intents/{intent_id}/selection` after the user chooses a product.
5. If the result is `ESCALATE`, call
   `POST /intents/{intent_id}/merchant-approval`, then have the merchant
   approve or reject it from the dashboard.
6. `POST /verify-purchase` with the persisted `intent_id`.
7. `POST /payments/create` with the same `intent_id` and an idempotency key.

For a typed preview of stages 3–5, call
`POST /intents/{intent_id}/orchestrate`. It returns the full decision trace and
next action without executing a payment.

The LLM endpoint uses OpenAI Structured Outputs with the model configured by
`OPENAI_INTENT_MODEL`. The deterministic endpoint remains available for local
development without API usage.
