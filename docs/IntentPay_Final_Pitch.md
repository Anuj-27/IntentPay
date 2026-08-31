# IntentPay Final Pitch

## One sentence

IntentPay is a deterministic authorization and trust control plane that lets AI
agents participate in commerce without giving the model unchecked control over
money.

## The problem

An AI can understand “buy Sony headphones below ₹5,000,” yet the final purchase
may still contain a changed product, quantity, price, subscription, merchant
policy conflict, duplicate payment, or uncertain provider result. A fluent model
response is not financial authorization evidence.

## The solution

IntentPay converts the request into a persisted Intent Mandate, filters hard
constraints before ranking, keeps meaningful trade-offs visible, separates
recommendation from selection, verifies the exact transaction, evaluates
merchant policy independently, and releases only Trust Gate `ALLOW` decisions
to a provider-neutral payment boundary.

## Why it is different

- The LLM extracts intent but never authorizes payment.
- The cheapest valid option cannot be silently hidden by ranking.
- Above-budget upgrades can be recommended but not executed.
- Subscription, quantity, price, product, merchant, and currency are rechecked.
- Idempotency and signed-event replay protection prevent duplicate effects.
- Timeouts become `UNKNOWN` and are reconciled instead of blindly retried.
- Every major decision has a structured reason code and correlated audit trail.

## Evidence in the repository

- 500 versioned synthetic purchase scenarios,
- zero unsafe ALLOWs in the current deterministic baseline,
- five reproducible demo stories,
- internal-ledger simulation plus a test-mode-only Razorpay adapter,
- raw webhook HMAC and Checkout signature verification,
- migration-backed payment/provider evidence,
- complete automated API and service regression coverage.

## Honest boundary

The repository is a strong buildathon proof, not a production payment system.
The synthetic benchmark is not real-user fairness evidence. Authentication,
rate limiting, immutable audit storage, frontend, deployment hardening, and a
credentialed Razorpay smoke test remain before production use. Live Razorpay
keys are rejected.

## Closing

> The question is no longer only whether AI can pay. The question is whether we
> can prove that every AI-assisted commercial action still matches human intent.
> IntentPay makes that proof deterministic, explainable, and provider-ready.

