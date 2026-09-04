from backend.app.schemas.merchant_policy import MerchantPolicy

merchant_policy = MerchantPolicy(
    merchant_id="MERCHANT-001",
    max_transaction_amount=10000,
    # Covers every single-quantity item in this merchant's own catalog
    # (₹3,200-₹5,500) so a routine purchase auto-allows instead of
    # escalating by default -- ESCALATE stays reserved for genuinely
    # larger/atypical totals (e.g. a multi-quantity purchase) between
    # here and the ₹10,000 hard ceiling above.
    autonomous_transaction_limit=6000,
    daily_autonomous_amount_limit=50000,
    daily_autonomous_transaction_limit=20,
)

tech_merchant_policy = MerchantPolicy(
    merchant_id="MERCHANT-002",
    max_transaction_amount=150000,
    autonomous_transaction_limit=100000,
    daily_autonomous_amount_limit=2000000,
    daily_autonomous_transaction_limit=100,
)

vision_merchant_policy = MerchantPolicy(
    merchant_id="MERCHANT-003",
    max_transaction_amount=150000,
    autonomous_transaction_limit=100000,
    daily_autonomous_amount_limit=2000000,
    daily_autonomous_transaction_limit=100,
)
