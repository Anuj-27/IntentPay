# IntentPay — Project Context, Purpose, Architecture, and Build Plan

## Current implementation snapshot — 31 August 2026

This document began as the original build plan. The repository has now moved
beyond several sections that are still written as design background.

Currently implemented and tested:

- deterministic natural-language intent extraction,
- optional OpenAI Structured Outputs intent extraction,
- persisted intent mandates,
- explicit product-selection confirmation for non-autonomous intents,
- quantity-aware filtering, ranking, budget stretch, and trade-offs,
- Buyer Agent orchestration with explicit recommendation and selection output,
- Proposed Purchase and Intent Verifier,
- Merchant Policy Engine and Trust Gate,
- Buyer Agent and Trust Gate evaluation audit events,
- PostgreSQL models and Alembic migrations,
- persistent payment idempotency and payment state transitions,
- webhook replay protection,
- persistent audit logs,
- automated regression tests.

Real Razorpay Test Mode calls, signed Razorpay webhook verification, merchant
capability APIs, frontend, and the larger evaluation suite remain future work.

## 1. Project Name

**IntentPay**

### One-line definition

IntentPay is an **AI-native commerce orchestration and trust layer** that helps an AI buyer safely transact with a merchant while ensuring that every commercial and money-related action remains aligned with the user's intent, merchant policy, and explicit authorization.

---

## 2. Buildathon Track

**Razorpay Buildathon — Track 01: AI Growth & Agentic Commerce**

The track focuses on two broad goals:

1. **Help merchants grow revenue using AI**
2. **Make merchants transactable by AI buyers end to end**

IntentPay is being designed to cover both.

### Our interpretation of the track

Most basic solutions may stop at:

```text
User asks AI to buy something
        ↓
AI finds product
        ↓
Checkout
        ↓
Payment
```

IntentPay goes deeper:

```text
Human Intent
      ↓
Intent Mandate
      ↓
Agent-Readable Merchant Catalog
      ↓
Hard Constraint Filter
      ↓
Preference & Value Engine
      ↓
Trade-off / Upsell / Budget Stretch Decisions
      ↓
Proposed Purchase
      ↓
Intent Verifier
      ↓
Merchant Policy Engine
      ↓
Trust Gate
      ↓
ALLOW / REASK / BLOCK / ESCALATE
      ↓
Razorpay Test Mode
      ↓
Payment State
      ↓
Audit Trail + Metrics
```

---

# 3. Why We Are Building IntentPay

AI agents are becoming capable of making recommendations, selecting products, and eventually initiating payments.

But there is a serious problem:

> **An AI agent understanding what a user wants is not the same as proving that the final transaction still matches what the user authorized.**

A user may say:

> "Buy wireless headphones under ₹5,000. Any brand is okay. Do not add a subscription."

An AI agent might initially choose a correct product.

But before payment:

- the price may change,
- quantity may accidentally change,
- the selected variation may become unavailable,
- a subscription may be added,
- the AI may choose a more expensive product only because it earns the merchant more,
- stock may change,
- the merchant may require human approval,
- the payment API may time out,
- the AI may accidentally issue the same payment twice.

A normal shopping assistant may not have a strong control layer for all of these situations.

IntentPay is being built to become that control layer.

---

# 4. Core Problem Statement

## Primary problem

**How can an AI agent make purchasing decisions for a user without losing user control, overspending, violating merchant policy, or performing an unintended financial action?**

## Secondary problem

**How can merchants still use AI for growth — recommendations, upsells, cross-sells, and campaigns — without turning the agent into an aggressive revenue-maximizing system that ignores customer intent?**

## Third problem

**How can every AI money action be explained and audited later?**

For example:

```text
Why did the AI choose this product?
Why was another product rejected?
Why was the user asked again?
Why was the transaction blocked?
Why was human approval required?
Did the user explicitly approve the final amount?
Was a duplicate payment prevented?
```

IntentPay is designed to answer these questions.

---

# 5. Purpose of IntentPay

The purpose of IntentPay is to provide a **safe decision and authorization layer between an AI commerce agent and the payment system**.

IntentPay should ensure:

- the AI understands the user's request,
- the request becomes structured and machine-verifiable,
- hard constraints are never silently violated,
- preferences are distinguished from mandatory requirements,
- recommendations are based on customer value first,
- upsells are transparent,
- above-budget options require renewed approval,
- merchant rules are respected,
- every decision has a reason code and explanation,
- risky or unclear actions are stopped,
- only verified actions reach Razorpay,
- duplicate financial actions are prevented,
- all important actions are auditable.

---

# 6. What IntentPay Is NOT

IntentPay is **not just a chatbot**.

It is also not:

- only a product recommender,
- only a checkout UI,
- only an upsell bot,
- only a payment gateway,
- only an LLM wrapper,
- a system that automatically spends up to the user's full budget,
- a merchant revenue optimizer that ignores customer value.

Razorpay remains the payment execution layer.

IntentPay sits before payment execution and decides whether an AI-proposed action is allowed to proceed.

---

# 7. The Core Design Principle

## User budget is a maximum, not a target.

If a user gives a ₹10,000 budget and a ₹5,800 product satisfies the requirement, IntentPay should not automatically choose a ₹9,500 product just because money remains available.

The system must consider:

```text
1. Hard user constraints
2. Explicit user preferences
3. Customer value
4. Marginal value of spending more
5. Merchant growth opportunity
```

Merchant revenue comes **after** user intent and customer value.

### Main rule

> **Optimize merchant revenue subject to user intent, authorization, merchant policy, and customer value.**

Not:

> Maximize merchant revenue at any cost.

---

# 8. Four Pillars of IntentPay

## BUY

Make a merchant transactable by an AI buyer end to end.

Includes:

- structured intent,
- catalog search,
- product selection,
- checkout proposal,
- payment execution,
- payment confirmation.

## GROW

Help merchants increase legitimate revenue.

Includes:

- explainable upsell,
- cross-sell,
- value-based upgrades,
- budget stretch recommendations,
- lightweight campaign orchestration.

## GUARD

Prevent unauthorized or unsafe AI actions.

Includes:

- hard constraint enforcement,
- merchant policy checks,
- intent verification,
- user re-approval,
- human escalation,
- duplicate-payment prevention,
- payment state safety.

## PROVE

Make every important action explainable and measurable.

Includes:

- reason codes,
- audit trail,
- failure handling,
- metrics,
- evaluation scenarios,
- agent-attributed revenue.

---

# 9. Important IntentPay Concepts

## 9.1 Intent Mandate

The Intent Mandate converts human language into structured authorization.

Example:

User:

> "Buy Sony headphones under ₹5,000. ANC and fast charging matter. No subscription. I want to choose before the final purchase."

Structured representation:

```json
{
  "product_category": "headphones",
  "max_budget": 5000,
  "quantity": 1,
  "color": null,
  "color_preference": "ANY",
  "brand": "Sony",
  "brand_preference": "EXACT",
  "subscription_allowed": false,
  "autonomous_selection_allowed": false,
  "priority": "BEST_VALUE",
  "preferred_features": [
    "ANC",
    "fast charging"
  ]
}
```

This is much easier to verify than free-form natural language.

---

## 9.2 Hard Constraints vs Preferences

IntentPay separates hard requirements from softer preferences.

### ANY

User does not care.

Example:

```text
Any color is fine.
```

```json
{
  "color": null,
  "color_preference": "ANY"
}
```

### PREFERRED

User prefers something but allows alternatives.

Example:

```text
I prefer black, but another color is okay.
```

### EXACT

Hard requirement.

Example:

```text
Black only.
```

If an EXACT constraint fails, the AI cannot silently substitute another option.

---

## 9.3 Recommendation Permission vs Purchase Authorization

A product can be useful enough to recommend while still being unauthorized for automatic purchase.

Example:

```text
User budget: ₹5,000
Authorized product: ₹4,800
Better product: ₹5,500
```

IntentPay may say:

> "A stronger product is available for ₹500 more. Would you like to increase your budget?"

But:

```text
Can recommend? YES
Can automatically purchase? NO
```

This is one of the most important IntentPay principles.

---

# 10. Current Decision Types

IntentPay uses four decision types:

```text
ALLOW
REASK
BLOCK
ESCALATE
```

## ALLOW

The action satisfies the relevant authorization and policy checks.

Example:

```text
Budget: ₹5,000
Final amount: ₹4,800
Correct quantity
No subscription
Valid product
```

## REASK

User input or renewed authorization is required.

Examples:

- price exceeds the authorized budget,
- a meaningful price/value trade-off exists,
- requested variation is unavailable,
- user did not delegate autonomous selection.

## BLOCK

The proposed action violates an explicit restriction.

Examples:

- user explicitly said "no subscription" but checkout includes a subscription,
- invalid or forbidden product,
- impossible transaction state.

## ESCALATE

The user's intent is valid, but merchant/system rules require human approval.

Example:

```text
User budget: ₹4,000
Product: ₹3,799
Merchant rule:
AI transactions over ₹3,500 require human approval.
```

Decision:

```text
ESCALATE
```

---

# 11. Current Implemented Backend

The backend is currently being built with:

- **Python**
- **FastAPI**
- **Pydantic**
- **Uvicorn**

Current API concepts include:

```text
GET  /health
POST /intents
GET  /products
POST /products/filter
```

---

# 12. Current Project Structure

Current/future structure is approximately:

```text
IntentPay/
│
├── backend/
│   ├── __init__.py
│   │
│   └── app/
│       ├── __init__.py
│       ├── main.py
│       │
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── intent.py
│       │   ├── product.py
│       │   ├── decision.py
│       │   └── purchase.py          # next stage
│       │
│       ├── data/
│       │   ├── __init__.py
│       │   └── products.py
│       │
│       └── services/
│           ├── __init__.py
│           ├── product_filter.py
│           ├── preference_engine.py
│           ├── budget_stretch.py
│           └── tradeoff_engine.py
│
├── frontend/
├── tests/
├── docs/
├── .env.example
├── .gitignore
└── README.md
```

---

# 13. Current Fake Merchant Catalog

We currently use a fake merchant catalog before adding PostgreSQL.

Example products include:

```text
PROD-001 — Sony Basic Wireless — ₹3,200
PROD-002 — Sony Premium Wireless — ₹4,800
PROD-003 — JBL Tune Wireless — ₹3,500
PROD-004 — Sony Ultra Wireless — ₹5,500
```

Products contain:

- product ID,
- name,
- category,
- price,
- brand,
- color,
- rating,
- features,
- stock state.

---

# 14. Hard Constraint Filter

The filter checks:

- category,
- maximum budget,
- stock,
- EXACT brand,
- EXACT color.

Example:

Intent:

```text
Category = headphones
Budget = ₹5,000
Brand = Sony EXACT
```

Results:

```text
PROD-001 → ALLOWED
PROD-002 → ALLOWED
PROD-003 → REJECTED: BRAND_MISMATCH
PROD-004 → REJECTED: BUDGET_EXCEEDED
```

---

# 15. Explainability Layer

Rejected products are not silently removed.

IntentPay records structured reasons.

Example:

```json
{
  "code": "BUDGET_EXCEEDED",
  "message": "Product price ₹5500 exceeds budget ₹5000."
}
```

Other reason codes include:

```text
CATEGORY_MISMATCH
BUDGET_EXCEEDED
OUT_OF_STOCK
BRAND_MISMATCH
COLOR_MISMATCH
```

Later these reason codes feed into higher-level decisions.

For example:

```text
BUDGET_EXCEEDED
      ↓
Budget Stretch Policy
      ↓
Possible REASK
```

---

# 16. Budget Stretch Policy

IntentPay supports above-budget recommendations without treating them as authorized purchases.

Current prototype configuration:

```text
MAX_STRETCH_PERCENT = 15%
MIN_RATING_GAIN = 0.1
MIN_NEW_FEATURES = 2
```

Example:

```text
User budget: ₹5,000
PROD-002: ₹4,800
PROD-004: ₹5,500
```

PROD-004 is:

```text
₹500 over budget
10% above budget
```

If it provides meaningful extra value, it can become:

```text
decision = REASK
```

The AI can recommend it but cannot purchase it until the user explicitly updates the authorization.

---

# 17. Preference & Value Engine (PVE)

The PVE ranks only products that survived hard constraints.

This separation is intentional:

```text
Filtering
= Is this product allowed?

Ranking
= Which allowed product best matches the user?
```

Current PVE dimensions include:

- rating,
- preferred feature matching,
- price efficiency,
- user priority.

Current priorities include:

```text
CHEAPEST
BEST_VALUE
HIGHEST_RATING
```

Example user preference:

```json
{
  "priority": "BEST_VALUE",
  "preferred_features": [
    "ANC",
    "fast charging"
  ]
}
```

For each product, PVE can produce an explainable score breakdown:

```json
{
  "rating_score": 37.6,
  "feature_score": 40,
  "price_score": 0.8
}
```

---

# 18. Meaningful Trade-off Engine

Even if PVE ranks a more expensive valid product first, IntentPay should not always choose it automatically.

Example:

```text
PROD-001 = ₹3,200
PROD-002 = ₹4,800
```

If PROD-002 ranks higher because it has:

- ANC,
- fast charging,
- better rating,

but costs ₹1,600 more, IntentPay detects a meaningful trade-off.

Current threshold:

```text
20% price difference
```

Difference:

```text
₹4,800 - ₹3,200 = ₹1,600
₹1,600 / ₹3,200 = 50%
```

If:

```text
autonomous_selection_allowed = false
```

IntentPay returns:

```text
REASK
```

and shows both options.

This preserves user agency.

---

# 19. Example Decision Experience

User asks:

> "Buy Sony wireless headphones under ₹5,000. ANC and fast charging matter. I want the best value, but let me choose the final product."

IntentPay may return:

```text
Recommended:
Sony Premium Wireless — ₹4,800
+ ANC
+ Fast charging
+ Higher rating

Alternative:
Sony Basic Wireless — ₹3,200
+ Saves ₹1,600
- No ANC
- Lower rating

Decision:
REASK

Reason:
Meaningful price-value trade-off.
```

The user remains in control.

---

# 20. Why Merchant Revenue Is Still Important

IntentPay is not anti-upsell.

It supports legitimate merchant growth.

Example:

```text
Base suitable option: ₹3,200
User-approved upgrade: ₹4,800
Incremental revenue: ₹1,600
```

That ₹1,600 can be recorded as:

```text
Agent-assisted upsell revenue
```

But the reason for recommending the upgrade must be customer value, not simply merchant margin.

---

# 21. Future Upsell & Cross-Sell Engine

Planned examples:

## Upsell

```text
Basic headphones → Premium headphones
```

## Cross-sell

```text
Running shoes
+
compatible running socks
```

IntentPay will check:

- remaining user budget,
- user permission,
- compatibility,
- meaningful benefit,
- total transaction amount,
- merchant policy.

An upsell can be offered without being automatically purchased.

---

# 22. Planned Campaign Orchestrator

A lightweight merchant growth module will identify bounded revenue opportunities.

Example:

```text
100 customers
      ↓
23 abandoned product purchase
      ↓
12 eligible for approved campaign
      ↓
AI proposes 5% recovery offer
      ↓
Merchant policy check
      ↓
Human approval if required
      ↓
Execute
      ↓
Measure conversions and revenue
```

Metrics may include:

```text
Campaign customers
Conversions
Revenue generated
Discount cost
Net incremental revenue
```

---

# 23. Implemented Module: Proposed Purchase

This module is implemented in `backend/app/schemas/purchase.py`.

Current system knows:

```text
What the user authorized
What the merchant sells
Which products are valid
Which product ranks best
```

But before payment, IntentPay also needs to know:

> **What exact transaction is the AI trying to execute?**

Planned schema:

```json
{
  "product_id": "PROD-002",
  "quantity": 1,
  "unit_price": 4800,
  "total_amount": 4800,
  "subscription": false
}
```

This is called the **Proposed Purchase**.

---

# 24. Implemented Intent Verifier

The Intent Verifier compares:

```text
Intent Mandate
       VS
Proposed Purchase
```

Initial rules:

## Quantity

```text
Authorized = 1
Proposed = 2
→ violation
```

## Budget

```text
Authorized max = ₹5,000
Proposed total = ₹5,200
→ REASK
```

## Subscription

```text
subscription_allowed = false
Proposed subscription = true
→ BLOCK
```

This is where IntentPay begins directly protecting a money action.

---

# 25. Implemented Merchant Policy Engine

User authorization alone is not enough.

The merchant also has rules.

Example:

```json
{
  "max_agent_transaction": 10000,
  "human_approval_above": 3500,
  "max_auto_discount_percent": 10
}
```

Example:

```text
User allows ₹3,799
Merchant requires human approval above ₹3,500
```

Result:

```text
ESCALATE
```

Not REASK, because the user is not the problem.

---

# 26. Implemented Trust Gate

Before calling Razorpay, IntentPay will combine:

```text
Intent verification
+
Merchant policy
+
Current product state
+
Authorization state
+
Payment state
```

Then return one final decision:

```text
ALLOW
REASK
BLOCK
ESCALATE
```

Only final `ALLOW` can reach payment execution.

---

# 27. Planned Razorpay Test Mode Integration

Razorpay Test Mode will be used for payment execution.

Planned flow:

```text
Verified Purchase
      ↓
Create Razorpay Order
      ↓
Checkout / Payment
      ↓
Webhook
      ↓
Verify payment state
      ↓
Update IntentPay state
```

No real money should be used during development.

---

# 28. Payment Reliability Problems IntentPay Will Handle

## Network timeout

A payment API timeout does not automatically mean payment failed.

IntentPay should:

```text
Timeout
   ↓
DO NOT create another payment immediately
   ↓
Check existing payment/order state
   ↓
Wait for webhook / query payment state
```

## Duplicate payment request

If the AI accidentally calls payment twice:

```text
same logical purchase
      ↓
idempotency protection
      ↓
only one financial effect
```

## Stock changed before payment

Revalidate before financial execution.

## Price changed before payment

If final price is above authorization:

```text
REASK
```

---

# 29. Implemented Payment Idempotency

IntentPay will use an idempotency concept so repeated calls do not create repeated financial effects.

Example:

```text
Intent ID = INT-1001
Logical payment key = PAY-INT-1001
```

Repeated payment creation requests should map to the same logical payment attempt instead of charging twice.

---

# 30. Implemented Payment State Machine

Current concept:

```text
CREATED
   ↓
VALIDATED
   ↓
PRODUCT_SELECTED
   ↓
VERIFICATION_REQUIRED
   ↓
ALLOW / REASK / BLOCK / ESCALATE
   ↓
PAYMENT_PENDING
   ↓
PAID / FAILED
```

Payment state will never be assumed based only on a network response.

---

# 31. Implemented Audit Trail Foundation

Every important action will be recorded.

Example:

```json
{
  "intent_id": "INT-4822",
  "requested_max_amount": 5000,
  "proposed_amount": 5299,
  "decision": "REASK",
  "reason": "MAX_AMOUNT_EXCEEDED",
  "payment_created": false
}
```

The audit trail should answer:

- what happened,
- why it happened,
- what data was used,
- what the agent wanted to do,
- whether the user approved it,
- whether merchant approval was required,
- whether money moved.

---

# 32. Implemented Database Foundation

The catalog remains in Python lists, while intents, payments, webhook events,
and audit logs are persisted through SQLAlchemy and PostgreSQL migrations.

Later:

```text
Python fake data
      ↓
PostgreSQL
```

Likely entities:

```text
users
merchants
products
intents
intent_events
merchant_policies
proposed_purchases
decisions
approvals
payments
payment_attempts
webhook_events
audit_events
campaigns
growth_metrics
```

---

# 33. Implemented Intent Extraction Foundation

The decision engine remains intentionally deterministic. Intent extraction is
available through both a deterministic parser and an optional OpenAI
Structured Outputs endpoint.

AI/LLM comes before it.

Future flow:

```text
"Buy Sony headphones under ₹5000.
ANC matters. No subscriptions."
        ↓
LLM
        ↓
Structured Intent Mandate
        ↓
Pydantic validation
        ↓
Deterministic IntentPay rules
```

Important principle:

> **LLM understands language. Deterministic backend rules authorize money actions.**

We do not want an LLM alone to decide whether a payment is safe.

---

# 34. Completed Buyer Agent Orchestration

The Buyer Agent orchestration layer is implemented. It converts a trusted
persisted Intent Mandate into either an explainable decision or an exact
Proposed Purchase.

The decision flow is:

1. Load the persisted Intent Mandate.
2. Apply hard product constraints.
3. Rank valid products using user preferences.
4. Calculate meaningful trade-offs and budget-stretch candidates.
5. Return BLOCK when no valid product exists.
6. Return REASK when explicit user selection is required.
7. Select automatically only when autonomous selection was authorized.
8. Create an exact Proposed Purchase.
9. Verify the proposal against the original intent.
10. Apply merchant policy and calculate the final Trust Gate decision.

The Buyer Agent keeps the agent's recommendation separate from the product
that the user selected. This makes it possible to explain when the agent
recommended one product but the user deliberately authorized another.

The Buyer Agent follows these safety rules:

- It does not trust mutable intent data supplied during execution.
- It never selects a product that failed a hard constraint.
- It respects an existing user-confirmed product.
- It includes quantity when calculating the proposed total.
- It does not invent subscription authorization.
- It never treats a budget-stretch recommendation as purchase authorization.
- Every Proposed Purchase must still pass deterministic verification.

Implemented endpoints:

- `POST /intents/{intent_id}/buyer-agent`
- `POST /intents/{intent_id}/buyer-agent/evaluate`

The evaluation response contains the Buyer Agent result, purchase verification,
intent decision, merchant-policy evaluation, final Trust Gate decision, and
the `ready_for_payment` status.

Buyer Agent decisions are stored as `BUYER_AGENT_DECISION` audit events. When
a Proposed Purchase reaches the Trust Gate, its result is also stored as a
`TRUST_GATE_PREVIEW_DECISION` event. REASK and BLOCK outcomes without a proposal
do not falsely claim that the Trust Gate ran.

Level 34 includes unit, API, Trust Gate, and audit integration coverage. At
this checkpoint, the complete test suite passes all 36 tests.

> **The Buyer Agent may propose a transaction, but only the deterministic
> Trust Gate can authorize it.**

---

# 35. Agent-Readable Merchant Layer

The merchant should expose structured information that AI agents can understand.

Example capabilities:

```json
{
  "merchant": "DemoStore",
  "capabilities": {
    "catalog_search": true,
    "inventory_check": true,
    "checkout": true,
    "refund": true
  },
  "policies": {
    "max_agent_transaction": 10000,
    "max_auto_discount_percent": 10,
    "human_approval_above": 7500
  }
}
```

This is more powerful than asking an AI to scrape arbitrary webpage HTML.

---

# 36. Protocol-Aware Design

IntentPay is intended to study and borrow useful principles from emerging agentic-commerce ecosystems and protocols such as:

- UAP
- ACP
- AP2
- x402

We should **not claim to implement these protocols unless the project actually implements the specifications**.

Instead, IntentPay can use protocol-inspired ideas such as:

```text
Structured intent mandate
Machine-readable merchant capability
Bounded authorization
Agent-to-agent commerce
Explicit payment authority
```

---

# 37. Example End-to-End Future Flow

```text
USER
"Buy Sony headphones under ₹5000.
ANC matters. No subscription."

        ↓

LLM Intent Agent

        ↓

INTENT MANDATE

        ↓

AGENT-READABLE CATALOG

        ↓

HARD CONSTRAINT FILTER

        ↓

PREFERENCE & VALUE ENGINE

        ↓

TRADE-OFF ENGINE

        ↓

USER CHOICE / AUTONOMOUS SELECTION

        ↓

PROPOSED PURCHASE

        ↓

INTENT VERIFIER

        ↓

MERCHANT POLICY ENGINE

        ↓

TRUST GATE

   ┌────┼─────┬─────────┐
   ↓    ↓     ↓         ↓
ALLOW REASK BLOCK  ESCALATE

        ↓ if ALLOW

RAZORPAY TEST MODE

        ↓

PAYMENT STATE MACHINE

        ↓

WEBHOOK

        ↓

POSTGRESQL

        ↓

AUDIT + METRICS
```

---

# 38. Problems IntentPay Specifically Solves

## Problem 1 — AI overspending

A budget is treated as a maximum authorization, not a spending target.

## Problem 2 — Silent substitution

EXACT requirements cannot be silently changed.

## Problem 3 — Unauthorized recurring payments

Subscription permission is explicit and defaults to false.

## Problem 4 — Merchant-first recommendations

Merchant revenue cannot override user intent.

## Problem 5 — Expensive upgrade bias

Meaningful price/value trade-offs are shown to the user unless autonomous selection was explicitly granted.

## Problem 6 — Above-budget recommendations

Useful stretch products may be recommended, but cannot be automatically purchased.

## Problem 7 — Poor explainability

Structured reason codes explain rejection and decisions.

## Problem 8 — Policy conflict

Merchant policy is checked separately from user authorization.

## Problem 9 — Payment duplication

Idempotency will prevent repeated logical actions from causing multiple charges.

## Problem 10 — Ambiguous payment state

IntentPay will not assume failure after a timeout.

## Problem 11 — Agent mistakes

Final proposed purchase is verified again before payment.

## Problem 12 — Lack of auditability

Every important money decision will have an audit trail.

---

# 39. Key Safety and Trust Rules

1. **Budget permission is not purchase permission.**
2. **Merchant permission is not user permission.**
3. **Recommendation permission is not payment authorization.**
4. **A timeout is not proof that payment failed.**
5. **User intent takes priority over merchant revenue.**
6. **Hard constraints cannot be overridden by ranking.**
7. **AI may recommend outside a hard constraint, but cannot execute outside it without renewed authorization.**
8. **Every final financial action must be revalidated.**
9. **Duplicate logical requests must not create duplicate financial effects.**
10. **Every important money action should be explainable and auditable.**

---

# 40. Current Development Progress

Approximate overall status:

```text
Core authorization and decision foundation: implemented
External commerce integration and user experience: still in progress
```

### Completed / mostly completed

- FastAPI setup
- Python virtual environment
- project structure
- Pydantic schemas
- Intent Mandate V1
- product schema
- fake merchant catalog
- hard constraint filtering
- rejection reasons
- Budget Stretch V1
- Preference & Value Engine V2
- explainable scoring
- meaningful price-value trade-off detection
- user autonomy flag
- DecisionType schema
- Proposed Purchase
- Intent Verifier
- Merchant Policy Engine
- Trust Gate
- persisted intent mandates
- explicit user product-selection confirmation
- PostgreSQL payment, webhook, intent, and audit models
- Alembic migrations
- payment idempotency
- payment state machine
- webhook replay protection
- audit persistence
- deterministic natural-language intent extraction
- optional OpenAI Structured Outputs extraction
- automated API and service regression tests
- dependency and environment setup documentation

### Remaining major work

- merchant capability APIs
- Razorpay Test Mode
- retries / payment uncertainty
- upsell/cross-sell execution
- campaign orchestrator
- frontend
- merchant dashboard
- synthetic evaluation dataset
- metrics
- deployment
- architecture diagrams
- 5-minute demo video
- final pitch

---

# 41. Planned Metrics

IntentPay should not only look good in a demo.

It should produce measurable results.

Possible evaluation:

```text
500 synthetic purchase scenarios
```

Cases may include:

- valid transaction,
- budget exceeded,
- quantity changed,
- wrong category,
- wrong brand,
- wrong color,
- subscription added,
- price changed,
- inventory changed,
- stale authorization,
- duplicate request,
- API timeout,
- merchant approval required,
- meaningful product trade-off,
- budget stretch opportunity.

Metrics:

```text
Valid purchases correctly allowed
Violations correctly blocked
REASK decisions
False blocks
Duplicate actions prevented
Failures safely recovered
Average decision latency
Agent-assisted upsell revenue
User reauthorization rate
Policy escalations
```

We should show only metrics generated by real test runs.

---

# 42. Planned Demo Story

A strong 5-minute demo can show:

## Scenario 1 — Normal purchase

```text
User intent
→ Product selection
→ Verification
→ Razorpay Test Mode
→ Payment success
```

## Scenario 2 — Meaningful trade-off

```text
₹3,200 valid option
vs
₹4,800 better-feature option
→ IntentPay REASKS
→ user remains in control
```

## Scenario 3 — Budget stretch

```text
Budget ₹5,000
Better product ₹5,500
→ recommendation allowed
→ purchase blocked until reauthorization
```

## Scenario 4 — Unauthorized subscription

```text
subscription_allowed = false
Agent proposes subscription = true
→ BLOCK
```

## Scenario 5 — Payment timeout / duplicate protection

```text
payment status unknown
→ do not blindly retry
→ verify state / webhook
→ prevent duplicate payment
```

---

# 43. Long-Term Vision

IntentPay can evolve from a Buildathon project into:

> **A policy, authorization, value, and trust control plane for AI-native commerce.**

Future AI systems may have:

```text
Buyer Agent
Merchant Agent
Payment Agent
Growth Agent
Risk Agent
```

IntentPay's role is to ensure that these agents can act around money without losing control, explainability, or authorization.

---

# 44. Why This Project Matters

The future problem is not only:

> "Can AI make a payment?"

The deeper problem is:

> **"Can we trust AI to make commercial decisions involving money while preserving user intent and business policy?"**

IntentPay is being built to answer that problem.

---

# 45. Guidance for Claude / Another AI Coding Assistant

When helping with this project:

1. **Do not replace the existing architecture with a generic shopping chatbot.**
2. Preserve the separation between:
   - Intent Mandate
   - Product
   - Proposed Purchase
   - Decision
   - Merchant Policy
   - Payment
3. Do not let the LLM itself be the final financial authorization engine.
4. Prefer deterministic backend checks for:
   - budget,
   - quantity,
   - subscriptions,
   - merchant limits,
   - state transitions,
   - payment execution.
5. Preserve the four decisions:
   - ALLOW
   - REASK
   - BLOCK
   - ESCALATE
6. User intent and authorization always come before merchant revenue.
7. A product may be recommended without being authorized for purchase.
8. Above-budget options require renewed authorization.
9. Significant price/value trade-offs should remain user-visible unless autonomous selection was explicitly granted.
10. Do not integrate real-money Razorpay flows during development; use Test Mode.
11. Add code incrementally rather than rewriting the whole repository.
12. Keep every important decision explainable through structured reason codes.
13. Future code should be production-oriented:
   - typed,
   - testable,
   - modular,
   - auditable,
   - secure,
   - idempotent.
14. Before modifying an existing file, first inspect the current implementation so previously completed logic is not accidentally removed.
15. The **Buyer Agent orchestration layer** is complete, including persisted
    intent loading, recommendation and selection separation, Proposed Purchase
    creation, Trust Gate evaluation, structured audit logs, and automated tests.
    The immediate next module is the **Agent-Readable Merchant Layer**.

---

# 46. Immediate Next Development Step

Build the Agent-Readable Merchant Layer on top of the completed Buyer Agent
foundation. The merchant should expose structured information for:

```text
Merchant identity
→ agent capabilities
→ product catalog
→ inventory availability
→ checkout capabilities
→ transaction limits
→ human-approval thresholds
→ refund and cancellation policies
```

The Buyer Agent should consume this structured merchant contract instead of
depending permanently on hard-coded merchant assumptions.

After the merchant layer is stable, integrate Razorpay Test Mode. The Razorpay
phase must add signed webhook verification, provider-order reconciliation,
timeout recovery, and end-to-end tests without weakening the existing
deterministic authorization checks.

---

# 47. Final Project Statement

**IntentPay is an AI-native commerce trust and orchestration layer designed to let AI buyers transact with merchants safely while enabling legitimate merchant growth. It converts human intent into structured authorization, filters and ranks merchant products, explains trade-offs, controls budget-stretch and upsell behavior, verifies the final proposed purchase, enforces merchant policy, and ensures that only explainable, bounded, gated, and auditable actions reach the payment layer.**
