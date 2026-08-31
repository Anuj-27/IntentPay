# Razorpay Test Mode Setup

IntentPay intentionally rejects Razorpay live keys. Complete these steps only
with a Razorpay Test Mode account; no real money is used in Test Mode.

## 1. Configure test credentials

Generate test keys in the Razorpay Dashboard and add them to `.env`:

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

The webhook secret is the separate secret chosen while configuring the webhook;
it is not the API key secret. Never commit `.env`.

Verify configuration without printing credentials:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/payments/razorpay-test/configuration
```

Expected result: `configured: true` and `test_mode_only: true`.

## 2. Apply migrations and start IntentPay

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

## 3. Create a trusted order

First persist an intent and, when autonomous selection is false, confirm a
product. Submit the exact verified purchase to:

```text
POST /payments/razorpay-test/orders
```

IntentPay runs the complete Trust Gate before loading provider credentials or
creating a local payment. A successful response contains verified
`checkout_options` with the public test key ID, paise amount, currency, and
Razorpay order ID.

The endpoint is idempotent. Replaying the same logical request returns the
existing order without sending another provider request.

## 4. Open Razorpay Checkout

Pass the returned `checkout_options` to Razorpay Standard Checkout. After the
browser returns `razorpay_order_id`, `razorpay_payment_id`, and
`razorpay_signature`, send them to:

```text
POST /payments/{local_payment_id}/razorpay-test/verify-checkout
```

IntentPay verifies `HMAC-SHA256(order_id|payment_id, key_secret)` on the server.
A valid Checkout signature does not mark the payment captured; fulfillment must
wait for a signed captured webhook or verified reconciliation.

## 5. Configure the signed webhook

Configure this endpoint in Razorpay Test Mode:

```text
POST https://your-public-host/webhooks/razorpay
```

Subscribe to:

- `payment.authorized`,
- `payment.captured`,
- `payment.failed`.

IntentPay verifies the HMAC over the untouched raw request body before parsing
JSON. It uses `X-Razorpay-Event-Id` for replay protection and validates provider
order ID, payment ID, amount in paise, and currency before changing state.
A `payment.failed` event records a failed attempt but leaves the order open,
because Razorpay Checkout may allow another attempt against the same order.

## 6. Reconcile uncertainty

Call:

```text
POST /payments/{local_payment_id}/razorpay-test/reconcile
```

When an order ID is known, IntentPay fetches that order. After a create-order
timeout, it searches by the deterministic receipt. State changes occur only
after ID, receipt, amount, and currency verification. The original order request
is never blindly retried.

## Current verification boundary

The adapter and its fake-provider regression suite are complete. A credentialed
Razorpay smoke test cannot be performed until you supply your own Test Mode
keys and public webhook URL. Live keys remain rejected by design.

Official references:

- https://razorpay.com/docs/api/orders/create/
- https://razorpay.com/docs/api/orders/fetch-all/
- https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/
- https://razorpay.com/docs/webhooks/validate-test/
