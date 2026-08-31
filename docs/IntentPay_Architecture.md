# IntentPay Architecture

## Trust and execution flow

```mermaid
flowchart TD
    U[User request] --> L[Deterministic or LLM intent extraction]
    L --> M[Persisted Intent Mandate]
    M --> C[Agent-readable merchant contract and catalog]
    C --> F[Hard constraint filter]
    F --> R[Preference and value ranking]
    R --> T[Trade-off and stretch analysis]
    T --> S{User selection or explicit autonomy}
    S --> P[Proposed Purchase]
    P --> I[Recommendation-integrity guard]
    I --> V[Exact Intent Verifier]
    V --> MP[Merchant Policy Engine]
    MP --> G{Trust Gate}
    G -->|REASK| U
    G -->|BLOCK| X[Stop]
    G -->|ESCALATE| H[Merchant human approval]
    G -->|ALLOW| B[Provider-neutral payment command]
    B --> IL[Internal ledger simulator]
    B --> RZ[Razorpay Test Mode adapter]
    RZ --> O[Razorpay order and Checkout]
    O --> CS[Server-side Checkout signature verification]
    O --> WH[Raw signed webhook]
    WH --> PS[Payment state machine]
    CS --> PS
    PS --> DB[(PostgreSQL)]
    DB --> A[Correlated audit trail and metrics]
```

The LLM-facing component ends at structured intent extraction. It cannot call a
provider directly. Only deterministic code behind the Trust Gate can construct
a provider command.

## Payment state and uncertainty

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> PENDING: provider submission
    CREATED --> FAILED: known rejection
    PENDING --> AUTHORIZED: signed provider event
    PENDING --> CAPTURED: signed captured event
    PENDING --> FAILED: known failure
    PENDING --> UNKNOWN: timeout or invalid provider result
    AUTHORIZED --> CAPTURED: capture confirmed
    AUTHORIZED --> UNKNOWN: status uncertain
    UNKNOWN --> PENDING: verified order still open
    UNKNOWN --> AUTHORIZED: verified authorization
    UNKNOWN --> CAPTURED: verified paid order or webhook
    UNKNOWN --> FAILED: verified failure
```

An `UNKNOWN` payment is never automatically retried. IntentPay fetches the
known provider order or searches by its deterministic receipt, then verifies
order ID, amount, currency, and receipt before reconciliation.

## Persisted financial evidence

```text
IntentDB
  intent_id, correlation_id, protocol_version, mandate, selected_product_id

PaymentDB
  payment_id, intent_id, product_id, amount, currency, idempotency_key
  provider, provider_order_id, provider_payment_id, provider_status, status

WebhookEventDB
  event_id, payment_id, provider, signature_verified, status, processed

AuditLogDB
  audit_id, component, decision, reason_code, amount, details, created_at
```

Secrets and signatures are not stored in audit details. Correlation IDs connect
intent, Trust Gate, payment, provider, webhook, and reconciliation evidence.

